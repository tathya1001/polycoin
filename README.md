# MoneyAngle

A personal bank-statement analyser. Import a statement, and each transaction's name, amount, balance and notes are stored encrypted with a key unique to your account. That key is locked with your password (and with a recovery key you keep), so the stored data can't be read without one of them, by the operator included. While you are signed in, the server unlocks it to compute your dashboards; logging out locks it again. The optional AI features run on an Ollama model on your own machine: your browser sends transaction text to it, and to no AI service.

> **Status:** a learning/portfolio project in active development. Setup and usage documentation is coming soon.

## License

[MIT](LICENSE)
