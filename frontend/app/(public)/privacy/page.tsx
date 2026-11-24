import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "@/components/shell/Logo";
import { CONTACT_EMAIL, OPERATOR_LOCATION, OPERATOR_NAME, policyDate } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy · MoneyAngle",
  description: "What MoneyAngle collects, why, how it is protected, and your rights.",
};

// Every statement here must stay true of the code: when a feature changes what is collected,
// stored, sent or kept, update this page and its version (lib/legal.ts and backend settings).

const SHORT_VERSION = [
  "We keep only what you import and what your account needs to work.",
  "Your transactions are encrypted with a key that only your password or recovery key can open.",
  "We never sell your data, use it for ads or send it to an AI company.",
  "No tracking or advertising cookies.",
  "You can download or delete everything, any time, in Settings.",
];

const COOKIES = [
  { name: "access", purpose: "Keeps you signed in. The sign-in inside it expires after 10 minutes and is renewed.", lasts: "7 days" },
  { name: "refresh", purpose: "Renews your sign-in.", lasts: "7 days" },
  { name: "vault", purpose: "Lets our server unlock your data for this browser only.", lasts: "7 days" },
  { name: "csrftoken", purpose: "Protects your account from forms on other websites.", lasts: "1 year" },
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-6 space-y-3">
      <h2 className="pt-4 text-xl font-semibold tracking-tight text-ink">{title}</h2>
      {children}
    </section>
  );
}

function Bullets({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-1.5 pl-5 marker:text-muted">{children}</ul>;
}

function Strong({ children }: { children: ReactNode }) {
  return <span className="font-medium text-ink">{children}</span>;
}

const LINK = "font-semibold text-ink underline underline-offset-4";

export default function PrivacyPolicy() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-5 sm:px-6">
      <nav className="flex items-center justify-between">
        <Link href="/" className="inline-flex" aria-label="MoneyAngle home">
          <Logo />
        </Link>
      </nav>

      <article className="space-y-4 pt-12 pb-16 leading-relaxed text-ink-2">
        <header className="space-y-2">
          <h1 className="text-[40px] leading-tight font-semibold tracking-tight text-ink">Privacy Policy</h1>
          <p className="text-sm text-muted">Last updated {policyDate()}</p>
        </header>

        <p>
          This policy explains what personal data MoneyAngle collects, why, how we protect it, and the rights you have
          over it. Please read it before you create an account.
        </p>

        <div className="rounded-md border-[1.5px] border-hairline bg-surface p-5">
          <p className="mb-2 font-semibold text-ink">The short version</p>
          <Bullets>
            {SHORT_VERSION.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </Bullets>
        </div>

        <Section id="who-we-are" title="1. Who we are">
          <p>
            MoneyAngle is a personal project run by one person, {OPERATOR_NAME}, an individual based in{" "}
            {OPERATOR_LOCATION}, India. In this policy, &ldquo;we&rdquo; and &ldquo;us&rdquo; mean {OPERATOR_NAME}. We
            decide how your personal data is used, so we are responsible for it. Under Indian law we are its Data
            Fiduciary.
          </p>
          <p>
            No one else works on MoneyAngle, and no one else on our side has access to its server, database or admin
            tools. The hosting providers in section 7 run the machines it lives on.
          </p>
          <p>
            MoneyAngle is free. We do not charge for it or earn money from it.
          </p>
          <p>
            MoneyAngle is not a bank or a financial adviser. It never connects to your bank: it only reads the
            statement files you choose to import. Nothing in MoneyAngle is financial advice.
          </p>
        </Section>

        <Section id="what-we-collect" title="2. What we collect">
          <p>
            <Strong>Your account.</Strong>
          </p>
          <Bullets>
            <li>Your email address, to sign you in.</li>
            <li>Your password, stored only as a one-way hash that cannot be turned back into the password.</li>
            <li>
              Your date of birth, only to check that you are 18 or older. It is stored encrypted and used for nothing
              else.
            </li>
            <li>When you signed up and last signed in, and which version of this policy you accepted and when.</li>
            <li>
              A record of each browser you are signed in on. It expires 7 days after you last use that browser, and
              is then cleared out.
            </li>
          </Bullets>
          <p>
            <Strong>What you import and create.</Strong>
          </p>
          <Bullets>
            <li>
              The transactions in your statements: date, description, amount, debit or credit, and balance.
              Descriptions can include the names and payment IDs of people and businesses you paid or were paid by.
            </li>
            <li>
              What you make in the app: categories, keywords, notes, data source names, dashboards, and the search
              index that the Ask feature uses.
            </li>
            <li>
              We do not keep your statement files. Excel and CSV files are read on our server, the transactions are
              saved, and the file is discarded. PDF files are read in your browser: only the transactions in them
              reach us, never the PDF itself. A file&apos;s password is used only to open that file and is never
              stored.
            </li>
          </Bullets>
          <p>
            <Strong>Technical data.</Strong>
          </p>
          <Bullets>
            <li>
              Server logs: your IP address, the time, the address requested (our server does not log search terms),
              the result and how long it took. We use them to keep MoneyAngle secure and to fix faults. Our hosting
              providers (section 7) keep logs of their own, under their own rules.
            </li>
            <li>
              Short-lived counters that stop abuse, such as repeated sign-in attempts. They are tied to your IP
              address or your account, and failed sign-ins are also counted under a scrambled (hashed) form of the
              email address, not the address itself. They are kept for up to one hour.
            </li>
          </Bullets>
          <p>
            We do not ask for your name, bank login, phone number or location, and we use no analytics, advertising
            or tracking tools. Please import only your own statements, or statements you have the right to use.
          </p>
        </Section>

        <Section id="how-we-use-it" title="3. How we use it">
          <p>We use your personal data only to:</p>
          <Bullets>
            <li>create and run your account, and sign you in;</li>
            <li>store, show and analyse your transactions: categories, dashboards and search;</li>
            <li>keep MoneyAngle secure, for example by limiting sign-in attempts;</li>
            <li>check that you are 18 or older;</li>
            <li>reply when you contact us, and meet our legal duties.</li>
          </Bullets>
          <p>
            We do not sell or rent your data, use it for advertising, share it with data brokers, use it to make
            credit or other decisions about you, or use it to train AI models.
          </p>
        </Section>

        <Section id="consent" title="4. Your consent">
          <p>
            When you create an account, you tick a box to accept this policy. That is your consent to the use of your
            data described here. You can withdraw it at any time by deleting your account in Settings or, if you
            cannot sign in, by asking us to delete it (section 11). Withdrawing does not affect what was done before,
            and MoneyAngle cannot keep working for you without the data it needs.
          </p>
        </Section>

        <Section id="security" title="5. How we protect it">
          <Bullets>
            <li>
              Your transactions and everything you create in the app are encrypted (AES-256-GCM) with a key that
              belongs to you alone. That key is locked with your password and with your recovery key.
            </li>
            <li>
              While you are signed in, our server unlocks your key to build your dashboards. When you log out, that
              copy is deleted and your data is locked again. If you don&apos;t log out, it expires 7 days after you last
              used MoneyAngle.
            </li>
            <li>
              Some details stay readable so the app can work: your email address, when records were created or
              changed, and display settings such as colours and dashboard layout.
            </li>
            <li>All traffic uses HTTPS, and your sign-in cookies cannot be read by scripts on the page.</li>
            <li>
              We cannot reset your password. If you lose both your password and your recovery key, nobody, including
              us, can open your data. All we can do then is delete your account (section 11).
            </li>
          </Bullets>
          <p>
            No system is perfectly secure, so we cannot promise that a breach will never happen. If one does, we will
            act quickly and tell you (section 12).
          </p>
        </Section>

        <Section id="ai" title="6. The AI features">
          <p>
            Categorize, Ask and the AI panel builder are optional. They use Ollama, a program you install on your own
            computer. MoneyAngle connects to it only at an address on your own computer, and we never send your data
            to an AI company.
          </p>
          <p>
            Ollama can also offer &ldquo;cloud&rdquo; models, which run on its maker&apos;s servers instead of your
            computer. If you choose one of those in MoneyAngle, your transaction text goes to those servers, under
            Ollama&apos;s own terms. To keep everything on your computer, choose a model that runs locally.
          </p>
          <p>
            When you use Ask, our server receives your question to search your transactions. It is used only to answer
            you and is not stored. The AI panel builder&apos;s conversation is not stored on our server either.
          </p>
        </Section>

        <Section id="sharing" title="7. Who we share it with">
          <p>
            We share personal data only with the service providers MoneyAngle relies on, and only what they need to do
            their job:
          </p>
          {/* No error-reporting service is used. If one is ever turned on in production, list it here. */}
          <Bullets>
            <li>a cloud hosting provider that runs our server, in Singapore;</li>
            <li>a database hosting provider that stores our database, in Singapore;</li>
            <li>
              a web hosting provider that delivers our pages and passes your requests to our server. Your data passes
              through its network, which has servers in many countries;
            </li>
            <li>
              a code-hosting service that builds MoneyAngle and applies its updates to our database. It does not
              receive copies of your data;
            </li>
            <li>an email service, which carries the messages you send us and our replies.</li>
          </Bullets>
          <p>
            These providers may use the data only to provide their service to us. We will also disclose data if the
            law requires it, for example to obey a valid court order or a lawful request from a government authority.
          </p>
          <p>
            If MoneyAngle is ever handed over to someone else or shut down, we will tell you in advance and give you
            time to download or delete your data.
          </p>
        </Section>

        <Section id="location" title="8. Where your data is stored">
          <p>
            Our server and database are in Singapore, so your data is stored and processed outside India. On its way
            to us, it may also pass through web servers in other countries. We will follow any limits that Indian law
            places on such transfers.
          </p>
        </Section>

        <Section id="cookies" title="9. Cookies and browser storage">
          <p>MoneyAngle uses only the cookies it needs to work:</p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b-[1.5px] border-hairline text-ink">
                  <th className="py-2 pr-4 font-semibold">Cookie</th>
                  <th className="py-2 pr-4 font-semibold">What it does</th>
                  <th className="py-2 font-semibold whitespace-nowrap">Kept for</th>
                </tr>
              </thead>
              <tbody>
                {COOKIES.map((cookie) => (
                  <tr key={cookie.name} className="border-b border-hairline align-top">
                    <td className="py-2 pr-4 font-mono text-ink">{cookie.name}</td>
                    <td className="py-2 pr-4">{cookie.purpose}</td>
                    <td className="py-2 whitespace-nowrap">{cookie.lasts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            We use no analytics, advertising or tracking cookies, so there is no cookie banner. Your browser also keeps
            some settings on your device: appearance, the sidebar, table column widths, dashboard filters, the last
            dashboard and data source you used, and your Ollama address and model choices. Logging out clears them.
          </p>
        </Section>

        <Section id="retention" title="10. How long we keep it">
          <Bullets>
            <li>Your account and data: until you delete them.</li>
            <li>
              <Strong>Delete all my data</Strong> (Settings) removes your transactions, dashboards, categories and data
              sources at once, then puts back the starter categories and one empty data source. Your account and
              settings stay.
            </li>
            <li>
              <Strong>Delete my account</Strong> (Settings), or a deletion you ask us for (section 11), removes your
              account and everything in it at once, and destroys your encryption key, so backup files you downloaded
              can no longer be opened.
            </li>
            {/* The database's history (restore) window setting. If the plan or the setting changes, update this. */}
            <li>
              Our database provider keeps a short rolling history of the database to recover from failures. Deleted
              data leaves that history within 6 hours.
            </li>
            <li>Server logs are kept for a short period set by our hosting providers, then deleted.</li>
            <li>If the law requires us to keep something longer, we keep only that, and only for as long as required.</li>
          </Bullets>
        </Section>

        <Section id="rights" title="11. Your rights">
          <p>You can:</p>
          <Bullets>
            <li>
              <Strong>Get a copy</Strong> of your data: Settings, Your data, Download backup. Sections 2 and 7 of this
              policy say what we hold and who it is shared with.
            </li>
            <li>
              <Strong>Correct it:</Strong> edit your transactions, categories and data sources in the app, and change
              your password in Settings.
            </li>
            <li>
              <Strong>Erase it:</Strong> Settings, Delete all my data or Delete my account.
            </li>
            <li>
              <Strong>Withdraw your consent:</Strong> delete your account in Settings, or ask us to delete it (below).
            </li>
            <li>
              <Strong>Nominate someone:</Strong> write to us from your account&apos;s email address with their name and
              email address. If you die or cannot act yourself, they can ask us to delete your account.
            </li>
            <li>
              <Strong>Complain:</Strong> write to us (section 14). If you are not satisfied with the answer, you can
              complain to the Data Protection Board of India.
            </li>
          </Bullets>
          <p>
            We do not change an account&apos;s email address or date of birth, and we do not take requests to change
            them. To use a different email address, delete your account and create a new one. Backup files from the
            old account cannot be opened in the new one.
          </p>

          <p className="pt-2">
            <Strong>If you cannot sign in.</Strong> If you forget your password,{" "}
            <Link href="/recover" className={LINK}>
              set a new one with your recovery key
            </Link>
            . If you have lost both your password and your recovery key, nobody can open your account or its data,
            including us, and we cannot reset your password or recover your data. We can only delete your account and
            everything in it. To ask for that:
          </p>
          <ol className="list-decimal space-y-1.5 pl-5 marker:text-muted">
            <li>Write to us (section 14) from the email address registered on the account.</li>
            <li>We reply to that address to check that the request is really yours.</li>
            <li>When you confirm, we delete the account and all its data, and tell you when it is done.</li>
          </ol>
          <p>You can then create a new account with the same email address.</p>
          <p>
            We answer every request within 30 days. To protect your account, we reply only to the email address
            registered on it.
          </p>
        </Section>

        <Section id="breaches" title="12. If something goes wrong">
          <p>
            If a security breach affects your personal data, we will tell you by email without undue delay: what
            happened, what it may mean for you, and what we are doing about it. We will also report it to the
            authorities where the law requires.
          </p>
        </Section>

        <Section id="children" title="13. Adults only">
          <p>
            You must be 18 or older to use MoneyAngle. We check your date of birth when you sign up. If we learn that
            someone under 18 has an account, we delete it.
          </p>
        </Section>

        <Section id="contact" title="14. Contact">
          <p>
            {OPERATOR_NAME} builds, owns and runs MoneyAngle, and personally handles every question, request and
            complaint about your personal data. Write to:
          </p>
          <address className="rounded-md border-[1.5px] border-hairline bg-surface p-5 not-italic">
            <Strong>{OPERATOR_NAME}</Strong>
            <br />
            Email:{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className={LINK}>
              {CONTACT_EMAIL}
            </a>
            <br />
            {OPERATOR_LOCATION}, India
          </address>
          <p>We reply within 30 days.</p>
        </Section>

        <Section id="changes" title="15. Changes to this policy">
          <p>
            When we update this policy, we change the date at the top. If a change is significant, we will tell you in
            the app or by email before it takes effect and, where the law requires, ask for your consent again.
          </p>
        </Section>
      </article>
    </main>
  );
}
