# mattia-inbox: Gmail assistant (Claude Managed Agents)

Every 30 minutes (07:00–22:30, Paris time) the agent checks Gmail and does the following:
- blocks certain spam and asks you about doubtful messages
- sends 👍 / one-line replies when that's all someone asked for
- drafts every other reply for you to review and send
- puts meetings on Google Calendar as tentative events
- emails a summary to mattiapuccetti311@gmail.com

You reply to the summary to answer its questions and approve new rules. It learns your style from what you actually send.

| File | What it is |
|---|---|
| `agent.md` | The agent: model, tools, and its full instructions (edit these to change its behavior) |
| `environment.yaml` | Its sandbox. It can reach only Google's sign-in, Gmail and Calendar servers |
| `vault.yaml` | The container for your Google credentials (the secrets are never in a file) |
| `memory_store-inbox.yaml` | Its memory between runs: rules, contacts, style, log |
| `deployment-every-30-min.yaml` | The 30-minute schedule, with a $1 cap per run |
| `scripts/` | Token helper, credential upload, test run, safety net for paused actions |

**EDHEC Outlook and Teams come in through Gmail** (setup step 1b). The agent summarizes them and writes a suggested reply for you to paste into Outlook or Teams. It never replies to them from Gmail. **WhatsApp is not included**, because personal accounts have no official API.

## Setup (once, on your computer)

**0. Tools.** Install the `ant` CLI (version 1.34 or later, from github.com/anthropics/anthropic-cli/releases) and run `ant auth login`. Then install the Python packages: `pip install anthropic google-auth-oauthlib`.

**1. Google app.** At console.cloud.google.com:
- Create a project and enable the **Gmail API** and the **Google Calendar API**.
- Under *OAuth consent screen*, choose External and add yourself as a test user.
- Under *Credentials*, create an **OAuth client ID** of type *Desktop app* and download it as `client_secret.json`.

**1b. Bring EDHEC into Gmail.** All three are optional, and EDHEC may block any of them. Test each one.
- **EDHEC mail:** in Outlook on the web, go to Settings → Mail → Forwarding (or Rules → "Redirect to"), forward to mattiapuccetti311@gmail.com and keep a copy. Send yourself a test email at your EDHEC address and check that it reaches Gmail.
- **Teams:** in Teams, go to Settings → Notifications → **Email**, and turn on emails for missed chats and mentions. They go to Outlook, then on to Gmail.
- **EDHEC calendar:** in Outlook calendar settings, go to Shared calendars → **Publish a calendar**, choose "Can view all details", and copy the **ICS** link. In Google Calendar, add it under Other calendars → **From URL**. The agent then checks it for clashes; it can only read it.

**2. Refresh token.** Run `python scripts/get_google_token.py client_secret.json > tokens.json` and sign in with your Gmail account.

**3. Create the agent.** From the repository root:
```sh
ant apply --dry-run -v agents/mattia-inbox/agent.md agents/mattia-inbox/environment.yaml agents/mattia-inbox/vault.yaml agents/mattia-inbox/memory_store-inbox.yaml
ant apply agents/mattia-inbox/agent.md agents/mattia-inbox/environment.yaml agents/mattia-inbox/vault.yaml agents/mattia-inbox/memory_store-inbox.yaml
```
This creates the agent, environment, vault and memory store, and writes their IDs into `claude-lock.json`. Keep that file; without it, the next `ant apply` creates duplicates.
```sh
export AGENT_ID=$(jq -r '.resources["./agents/mattia-inbox/agent.md"].id' claude-lock.json)
export ENV_ID=$(jq -r '.resources["./agents/mattia-inbox/environment.yaml"].id' claude-lock.json)
export VAULT_ID=$(jq -r '.resources["./agents/mattia-inbox/vault.yaml"].id' claude-lock.json)
export MEMORY_STORE_ID=$(jq -r '.resources["./agents/mattia-inbox/memory_store-inbox.yaml"].id' claude-lock.json)
```
(If a key doesn't match, use the path exactly as the `ant apply` plan printed it.)

**4. Store the credentials.** Run `python scripts/add_credentials.py tokens.json`, then **delete `tokens.json`**. Then put the vault ID into `deployment-every-30-min.yaml`, so that `vault_ids: ["vlt_..."]`.

**5. Test before you schedule it.**
- `python scripts/test_run.py` is a **dry run**. It reads your inbox, builds its first picture of your style and contacts, and prints what it *would* do with the last 24 hours of mail. It changes nothing. Check the categories and the drafted replies; if something is off, edit `agent.md`, run `ant apply` again, and repeat.
- `python scripts/test_run.py --live` does one real run, while you watch and approve anything it pauses on.

**6. Turn on the schedule.**
```sh
ant apply agents/mattia-inbox/deployment-every-30-min.yaml
```

**7. Safety net.** If a scheduled run hits an action that Anthropic's safety check can't judge, the run pauses and waits for a person. Run `python scripts/deny_paused.py` from time to time, or as a cron job on your computer. It denies those actions, so the agent skips them and asks you in the next summary.

## Changing things later

- **Its behavior:** edit `agent.md`, then `ant apply agents/mattia-inbox/agent.md`.
- **Schedule or cost cap:** edit the deployment file, then `ant apply` it.
- **Pause it:** `ant beta:deployments pause --deployment-id <depl_...>`. Use `unpause` to resume.
- **What it has learned:** its memory files are visible in the Console under Memory stores, and every change is versioned.
