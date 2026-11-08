import json
import os
import sys
import time
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from ai.eval import judge
from ai.eval.embed import DEFAULT_URL, TIMEOUT, ipv4_url


class Command(BaseCommand):
    help = (
        "Score a saved answers run with a judge model on a local Ollama (dev machine, fictional "
        "data). Scores are cached per model and prompt version: only answers not scored yet are "
        "sent, so a rerun is free. With --labelled, only the answers in the labelling sheets "
        "given on standard input."
    )

    def add_arguments(self, parser):
        parser.add_argument("--model", required=True, help="The judge, e.g. qwen2.5:7b.")
        parser.add_argument("--run", required=True, metavar="LABEL", help="A saved answers run.")
        parser.add_argument("--prompt", choices=judge.PROMPTS, default=judge.DEFAULT_PROMPT)
        parser.add_argument(
            "--labelled", action="store_true", help="Only the sheets' items (read from stdin)."
        )
        parser.add_argument(
            "--think",
            action="store_true",
            help="Let a model that can reason before it answers do so (much slower on a CPU).",
        )
        parser.add_argument("--url", default=os.environ.get("OLLAMA_URL", DEFAULT_URL))

    def handle(self, *args, **options):
        model, run, prompt = options["model"], options["run"], options["prompt"]
        try:
            items = judge.items_from_run(run)
        except FileNotFoundError as problem:
            raise CommandError(str(problem)) from None
        if options["labelled"]:
            wanted = set(judge.read_labels(sys.stdin.read()))
            items = [item for item in items if item.question_id in wanted]
        base = ipv4_url(options["url"])
        think = options["think"] if "thinking" in self._capabilities(base, model) else None
        cached = judge.load_judgments(model, run, prompt)
        # Scores the rubric decides without a model are stored first, so no call is made for them.
        ruled = 0
        for item in items:
            decided = judge.ruled(item, prompt)
            entry = cached.setdefault(item.question_id, {}) if decided else {}
            if decided and any(entry.get(key) != value for key, value in decided.items()):
                entry.update(decided)
                ruled += 1
        if ruled:
            judge.save_judgments(model, run, cached, prompt)
            self.stdout.write(f"{ruled} answers scored by the rubric's rules, without a model")
        # One metric at a time over every answer: the system prompt stays the same from call to
        # call, so Ollama reuses its cached prefix instead of reading it again.
        for metric in judge.call_metrics(prompt):
            done = "faithful" if metric == "both" else metric
            todo = [item for item in items if done not in cached.get(item.question_id, {})]
            self.stdout.write(
                f"{model} ({prompt}, {metric}) on {run}: {len(items) - len(todo)} cached, "
                f"{len(todo)} to judge"
            )
            for number, item in enumerate(todo, start=1):
                messages, schema = next(
                    (m, s) for name, m, s in judge.judge_calls(item, prompt) if name == metric
                )
                started = time.perf_counter()
                reply = self._chat(base, model, messages, schema, think)
                try:
                    scored = judge.read_reply(metric, reply, item, prompt)
                except (ValueError, KeyError, TypeError):
                    self.stdout.write(f"  {item.question_id}: unreadable reply, skipped")
                    continue
                seconds = round(time.perf_counter() - started, 1)
                entry = cached.setdefault(item.question_id, {})
                entry.update(scored)
                entry[f"{done}_seconds" if prompt != "v1" else "seconds"] = seconds
                judge.save_judgments(model, run, cached, prompt)  # a stop loses nothing
                self.stdout.write(
                    f"  [{number}/{len(todo)}] {item.question_id}: "
                    + ", ".join(f"{m} {scored[m]}" for m in judge.METRICS if m in scored)
                    + f" ({seconds} s)"
                )

    @staticmethod
    def _post(base: str, path: str, body: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            f"{base}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def _capabilities(self, base: str, model: str) -> list[str]:
        return self._post(base, "/api/show", {"model": model}, TIMEOUT).get("capabilities", [])

    def _chat(
        self, base: str, model: str, messages: list[dict], schema: dict, think: bool | None
    ) -> str:
        body = {
            "model": model,
            "messages": messages,
            "format": schema,
            "options": judge.JUDGE_OPTIONS,
            "stream": False,
        }
        if think is not None:  # only models that can reason accept the switch
            body["think"] = think
        return self._post(base, "/api/chat", body, TIMEOUT * 10)["message"]["content"]
