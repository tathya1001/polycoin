import sys

from django.core.management.base import BaseCommand, CommandError

from ai.eval import judge, results


class Command(BaseCommand):
    help = (
        "How far each judge model agrees with the labels in the sheets given on standard input, "
        "from cached scores (no model is called): on the tuning set (L items, which judge prompts "
        "may be tuned on) and the held-out set (H items, which they never are). Also judge-to-"
        "judge agreement, a panel of the judges, and a check against the made-up-number flags."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run", required=True, metavar="LABEL", help="The answers run judged.")
        parser.add_argument("--models", required=True, help="Judge models, comma separated.")
        parser.add_argument(
            "--prompt",
            default=judge.DEFAULT_PROMPT,
            help="A prompt version, or several comma separated (e.g. v3,v4): each answer's scores "
            "are then also averaged across the prompts, like a panel of judges.",
        )
        parser.add_argument(
            "--baseline",
            metavar="MODEL@PROMPT",
            help="Compare every judge with these cached scores, e.g. qwen2.5:7b@v1: the change "
            "in kappa on the same answers, with a paired bootstrap interval.",
        )
        parser.add_argument("--record", metavar="LABEL", help="Save the result for the report.")

    def handle(self, *args, **options):
        run, prompt = options["run"], options["prompt"]
        prompts = [p for p in prompt.split(",") if p]
        if not prompts or any(p not in judge.PROMPTS for p in prompts):
            raise CommandError(f"--prompt takes versions from {', '.join(judge.PROMPTS)}")
        models = [m for m in options["models"].split(",") if m]
        baseline = None
        if options["baseline"]:
            base_model, _, base_prompt = options["baseline"].rpartition("@")
            if base_prompt not in judge.PROMPTS or not base_model:
                raise CommandError("--baseline is MODEL@PROMPT, e.g. qwen2.5:7b@v1")
            baseline = judge.load_judgments(base_model, run, base_prompt)
        labels = judge.read_labels(sys.stdin.read())
        filled = {
            q: v
            for q, v in labels.items()
            if v["faithful"] is not None and v["relevant"] is not None
        }
        sets = {
            "tuning": {q: v for q, v in filled.items() if not v["held_out"]},
            "held-out": {q: v for q, v in filled.items() if v["held_out"]},
        }
        judges = [(m, p) for m in models for p in prompts]
        scores = {
            m if len(prompts) == 1 else f"{m}@{p}": judge.load_judgments(m, run, p)
            for m, p in judges
        }
        if len(judges) > 1:
            scores["panel"] = judge.panel(list(scores.values()))
        flagged = {
            r["question"] for r in results.load("answers", run)["results"] if r.get("made_up")
        }
        described = "; ".join(f"{p}: {judge.PROMPTS[p]}" for p in prompts)
        self.stdout.write(
            f"Prompt {described}. Answers run: {run}. Labels: "
            f"{len(sets['tuning'])} tuning, {len(sets['held-out'])} held-out.\n"
        )
        report = {"labels": {name: len(s) for name, s in sets.items()}, "judges": {}}
        for model, judged in scores.items():
            name = (
                f"panel of {' + '.join(k for k in scores if k != 'panel')}"
                if model == "panel"
                else model
            )
            self.stdout.write(f"{name} ({len(judged)} answers judged):")
            per_set = {}
            for set_name, reference in sets.items():
                per_metric = {m: judge.agreement(reference, judged, m) for m in judge.METRICS}
                per_set[set_name] = per_metric
                for metric, a in per_metric.items():
                    if not a["n"]:
                        continue
                    verdict = "reliable" if a["kappa"] >= judge.RELIABLE_KAPPA else "NOT reliable"
                    self.stdout.write(
                        f"  {set_name:8} {metric:8}: kappa {a['kappa']:.3f} "
                        f"[{a['kappa_ci'][0]:.3f}, {a['kappa_ci'][1]:.3f}] ({verdict}), exact "
                        f"{a['exact']:.0%}, within 1 {a['within_1']:.0%}, mean labels "
                        f"{a['mean_reference']} vs judge {a['mean_judged']} (n {a['n']})"
                    )
                    # Scores a rubric rule decided agree by design; show the model's share alone.
                    by_model = {q: v for q, v in judged.items() if f"{metric}_rule" not in v}
                    if len(by_model) < len(judged):
                        b = judge.agreement(reference, by_model, metric)
                        if b["n"]:
                            self.stdout.write(
                                f"  {'':8} {'':8}  scored by the model only: kappa "
                                f"{b['kappa']:.3f} [{b['kappa_ci'][0]:.3f}, "
                                f"{b['kappa_ci'][1]:.3f}], exact {b['exact']:.0%} (n {b['n']})"
                            )
                            per_metric[metric]["model_only"] = b
                    if baseline is not None:
                        c = judge.kappa_change(reference, baseline, judged, metric)
                        if c["n"] >= 2:
                            kind = "a real change" if c["real"] else "could be noise"
                            self.stdout.write(
                                f"  {'':8} {'':8}  vs {options['baseline']}: {c['before']:.3f} "
                                f"-> {c['after']:.3f}, change {c['change']:+.3f} "
                                f"[{c['change_ci'][0]:+.3f}, {c['change_ci'][1]:+.3f}] "
                                f"({kind}, paired, n {c['n']})"
                            )
                            per_metric[metric]["vs_baseline"] = c
            report["judges"][model] = per_set
            low = [
                judged[q]["faithful"] for q in judged if q in flagged and "faithful" in judged[q]
            ]
            high = [
                judged[q]["faithful"]
                for q in judged
                if q not in flagged and "faithful" in judged[q]
            ]
            if low and high:
                self.stdout.write(
                    f"  faithful, answers flagged with a made-up number: mean "
                    f"{sum(low) / len(low):.2f} (n {len(low)}) vs not flagged "
                    f"{sum(high) / len(high):.2f} (n {len(high)})"
                )
                report["judges"][model]["flagged_vs_not"] = [
                    round(sum(low) / len(low), 2), round(sum(high) / len(high), 2)
                ]  # fmt: skip
        if len(judges) == 2:
            first, second = (scores[k] for k in scores if k != "panel")
            for metric in judge.METRICS:
                a = judge.agreement(first, second, metric)
                if a["n"]:
                    self.stdout.write(
                        f"Judge vs judge, {metric}: kappa {a['kappa']:.3f} (n {a['n']})"
                    )
                    report.setdefault("judge_vs_judge", {})[metric] = a["kappa"]
        if options["record"]:
            headline = {f"labels {name}": len(s) for name, s in sets.items()}
            for model, per_set in report["judges"].items():
                for set_name in sets:
                    for metric in judge.METRICS:
                        if per_set[set_name][metric].get("n"):
                            key = f"{model} {set_name} {metric} kappa"
                            headline[key] = per_set[set_name][metric]["kappa"]
            path = results.save(
                "judge",
                options["record"],
                {"meta": results.metadata(answers_run=run, rubric=judge.RUBRIC_VERSION,
                                          prompt=prompt, models=models),
                 "headline": headline, "report": report},
                overwrite=True,
            )  # fmt: skip
            self.stdout.write(f"Saved {path.name}")
