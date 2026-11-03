"""Step 5 of the README: a supervised test run that you watch live in your terminal.

    export AGENT_ID=agent_... ENV_ID=env_... VAULT_ID=vlt_... MEMORY_STORE_ID=memstore_...
    python test_run.py            # dry run: reads and reports, changes nothing in Gmail
    python test_run.py --live     # one real run, with you approving any paused action

The IDs come from claude-lock.json after `ant apply` (README step 3).
"""

import os
import sys

import anthropic

DRY_RUN_PROMPT = """This is a DRY RUN. Do not send, draft, label, move, block, or create anything in Gmail or Calendar.
1. Check you can get an access token and read the inbox (list the 3 most recent subjects).
2. If memory is empty, build style.md and contacts.md from Sent as described.
3. Take the inbox messages from the last 24 hours and, for each one, write the category you would choose,
   what you would do, and (for replies) the text you would send or draft.
Print all of this here as your final message instead of emailing it."""

LIVE_PROMPT = (
    "Run your inbox check now: handle Mattia's replies to earlier summaries, then the new mail since the "
    "last run, then send the summary if there is anything to report."
)


def main() -> None:
    live = "--live" in sys.argv
    client = anthropic.Anthropic()

    session = client.beta.sessions.create(
        agent=os.environ["AGENT_ID"],
        environment_id=os.environ["ENV_ID"],
        vault_ids=[os.environ["VAULT_ID"]],
        resources=[{
            "type": "memory_store",
            "memory_store_id": os.environ["MEMORY_STORE_ID"],
            "access": "read_write",
        }],
        budget={"type": "limit", "max_list_cost": {"amount": "200", "currency": "USD"}},  # $2 cap
        title="mattia-inbox live test" if live else "mattia-inbox dry run",
    )
    print(f"Watch live: https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message",
                     "content": [{"type": "text", "text": LIVE_PROMPT if live else DRY_RUN_PROMPT}]}],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
            elif event.type == "agent.tool_use" and event.evaluated_permission == "ask":
                print(f"\n\n--- The agent wants to run {event.name}:\n{event.input}\n")
                ok = input("Allow? [y/N] ").strip().lower() == "y"
                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{
                        "type": "user.tool_confirmation",
                        "tool_use_id": event.id,
                        "result": "allow" if ok else "deny",
                        **({} if ok else {"deny_message": "Mattia denied this action. Skip it and mention it in the summary."}),
                    }],
                )
            elif event.type == "session.status_idle":
                if event.stop_reason.type != "requires_action":
                    print(f"\n\n--- Finished ({event.stop_reason.type}).")
                    break
            elif event.type == "session.status_terminated":
                print("\n\n--- Session ended.")
                break


if __name__ == "__main__":
    main()
