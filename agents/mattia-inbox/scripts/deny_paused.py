"""Safety net for the scheduled runs, which nobody is watching live.

If Anthropic's safety check can't decide whether an action is safe, the session pauses and waits for a person.
This script finds those paused calls and DENIES them, so the agent skips the action and reports it in the
summary instead of waiting forever. Run it whenever you like, or put it on a cron on your own computer:

    export AGENT_ID=agent_...
    python deny_paused.py

(To have Anthropic call you instead of polling, register a webhook for `session.status_idled` in
Console -> Manage -> Webhooks and call deny_paused_calls(session_id) from the handler.)
"""

import os

import anthropic

client = anthropic.Anthropic()


def deny_paused_calls(session_id: str) -> int:
    events = list(client.beta.sessions.events.list(session_id=session_id))
    answered = {e.tool_use_id for e in events if e.type == "user.tool_confirmation"}
    pending = [
        e for e in events
        if e.type == "agent.tool_use" and e.evaluated_permission == "ask" and e.id not in answered
    ]
    if pending:
        client.beta.sessions.events.send(
            session_id=session_id,
            events=[{
                "type": "user.tool_confirmation",
                "tool_use_id": e.id,
                "result": "deny",
                "deny_message": "No one was available to approve this action. Skip it and list it under "
                                "'Questions for you' in the summary.",
            } for e in pending],
        )
    return len(pending)


def main() -> None:
    agent_id = os.environ["AGENT_ID"]
    for session in client.beta.sessions.list():
        if session.status != "idle" or getattr(session.agent, "id", None) != agent_id:
            continue
        n = deny_paused_calls(session.id)
        if n:
            print(f"{session.id}: denied {n} paused action(s)")


if __name__ == "__main__":
    main()
