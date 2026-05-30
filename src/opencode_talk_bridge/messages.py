"""Localised user-facing strings (i18n).

A tiny catalog keyed by message id, with German (default) and English. The
bridge builds a translator via ``translator(BOT_LOCALE)`` and calls
``self._t("key", **fields)``. Unknown locales fall back to German; unknown keys
fall back to the key itself.
"""

from __future__ import annotations

from collections.abc import Callable

DE: dict[str, str] = {
    "working": "🔧 OpenCode arbeitet …",
    "busy": "⏳ Ich arbeite noch an der vorherigen Anfrage – bitte warten oder /stop.",
    "down": "⚠️ OpenCode ist nicht erreichbar. Bitte den Server prüfen.",
    "error": "⚠️ Fehler: {error}",
    "no_answer": "(keine Antwort)",
    "aborted": "🛑 Abgebrochen.",
    "attached_as_file": "📎 Antwort als Datei angehängt.",
    "session_error": "⚠️ OpenCode meldet einen Fehler.",
    "thinking": "💭 denkt nach …",
    "bg_done": "✅ Hintergrund-Session fertig.",
    # sessions
    "new_session": "🆕 Neue OpenCode-Session beim nächsten Prompt.",
    "session_is": "Session: {sid}",
    "no_session_yet": "Noch keine Session.",
    "no_session": "Keine Session.",
    "no_running_session": "Keine laufende Session.",
    "session_switched": "✅ Session gewechselt: {sid}",
    "detached": "🔌 Von der Session getrennt. Der nächste Prompt startet eine neue.",
    "no_sessions": "Keine Sessions vorhanden. Schreib einfach einen Prompt.",
    "rename_usage": "Nutzung: /rename <neuer Titel>",
    "no_session_rename": "Keine Session zum Umbenennen.",
    "renamed": "✅ Umbenannt: {title}",
    # model / agent
    "model_format": "Format: /model providerID/modelID",
    "model_set": "✅ Modell gesetzt: {model}",
    "model_current": "Aktuelles Modell: {model}\nSetzen: /model providerID/modelID",
    "agent_set": "✅ Agent gesetzt: {agent}",
    "no_agents": "Keine Agenten verfügbar. Setzen: /agent <name>",
    # pickers
    "pick_number": "_Antworte mit der Nummer._",
    "nothing_to_pick": "Nichts zur Auswahl.",
    "title_sessions": "🗂 Sessions:",
    "title_models": "🧠 Modelle:",
    "title_agents": "🎭 Agenten:",
    "title_projects": "📁 Projekte:",
    "title_worktrees": "🌿 Worktrees:",
    "title_commands": "⚡ Commands:",
    "title_skills": "🧩 Skills:",
    "title_mcps": "🔌 MCP-Server:",
    "title_messages": "💬 Nachrichten:",
    "title_action": "Aktion:",
    "no_projects": "Keine Projekte gefunden.",
    "no_worktrees": "Keine Worktrees gefunden.",
    "no_commands": "Keine Commands verfügbar.",
    "no_skills": "Keine Skills verfügbar.",
    "no_mcps": "Keine MCP-Server konfiguriert.",
    "no_messages": "Keine Nachrichten.",
    "dir_switched": "✅ {kind} gewechselt: {directory}\nNeue Session beim nächsten Prompt.",
    "reverted": "↩️ Zurückgesetzt.",
    "mcp_toggled": "🔌 {name} {state}.",
    "mcp_on": "aktiviert",
    "mcp_off": "deaktiviert",
    "action_revert": "↩️ Revert (hierhin zurück)",
    "action_fork": "🍴 Fork (neue Session ab hier)",
    # permission / question
    "perm_once": "🔐 erlaubt (einmal).",
    "perm_always": "🔐 erlaubt (immer).",
    "perm_reject": "🔐 abgelehnt.",
    "answered": "✅ {answer}",
    # tts
    "tts_unconfigured": "TTS ist nicht konfiguriert (TTS_API_URL / TTS_API_KEY).",
    "tts_on": "🔊 Sprachausgabe aktiviert.",
    "tts_off": "🔊 Sprachausgabe deaktiviert.",
    # scheduled tasks
    "no_scheduler": "Geplante Aufgaben sind nicht aktiv.",
    "task_usage": "Nutzung: /task <Minuten> <Prompt>  oder  /task every <Minuten> <Prompt>",
    "task_limit": "Limit erreicht ({limit} Aufgaben). Erst eine löschen (/tasklist).",
    "task_created": "⏰ Aufgabe geplant (in {minutes} min).",
    "task_none": "Keine geplanten Aufgaben.",
    "task_deleted": "🗑 Aufgabe gelöscht.",
    "title_tasks": "⏰ Geplante Aufgaben:",
    # status
    "status": "📊 OpenCode: {health}\nSession: {sid}\nModell: {model}\nAgent: {agent}",
    "reachable": "✅ erreichbar",
    "unreachable": "⚠️ nicht erreichbar",
    "help": (
        "🤖 *opencode-talk-bridge*\n"
        "Schreib eine Nachricht, um OpenCode zu prompten. Befehle:\n"
        "• /new — neue OpenCode-Session\n"
        "• /session — aktuelle Session-ID anzeigen\n"
        "• /sessions — Sessions auflisten & wechseln\n"
        "• /rename <Titel> — aktuelle Session umbenennen\n"
        "• /detach — von der Session trennen\n"
        "• /messages — Nachrichten durchsuchen, dann Revert/Fork\n"
        "• /model [providerID/modelID] — Modell anzeigen/wählen/setzen\n"
        "• /agent [name] — Agent anzeigen/wählen/setzen (plan/build)\n"
        "• /projects — OpenCode-Projekt wechseln\n"
        "• /worktree — Git-Worktree wechseln\n"
        "• /commands — eigene OpenCode-Commands ausführen\n"
        "• /skills — OpenCode-Skills ausführen\n"
        "• /mcps — MCP-Server aktivieren/deaktivieren\n"
        "• /tts — Sprachausgabe umschalten (falls konfiguriert)\n"
        "• /task <Min> <Prompt> — Aufgabe planen (/task every <Min> … für wiederkehrend)\n"
        "• /tasklist — geplante Aufgaben anzeigen/löschen\n"
        "• /stop — aktuellen Lauf abbrechen\n"
        "• /status — Bridge- & OpenCode-Status\n"
        "• /help — diese Nachricht\n"
        "Picker: mit der Nummer antworten. Permission: `ja` (einmal), "
        "`immer` (immer), `nein` (ablehnen)."
    ),
}

EN: dict[str, str] = {
    "working": "🔧 OpenCode is working …",
    "busy": "⏳ Still working on the previous request – please wait or /stop.",
    "down": "⚠️ OpenCode is unreachable. Please check the server.",
    "error": "⚠️ Error: {error}",
    "no_answer": "(no answer)",
    "aborted": "🛑 Aborted.",
    "attached_as_file": "📎 Answer attached as a file.",
    "session_error": "⚠️ OpenCode reported an error.",
    "thinking": "💭 thinking …",
    "bg_done": "✅ Background session finished.",
    "new_session": "🆕 New OpenCode session on the next prompt.",
    "session_is": "Session: {sid}",
    "no_session_yet": "No session yet.",
    "no_session": "No session.",
    "no_running_session": "No running session.",
    "session_switched": "✅ Session switched: {sid}",
    "detached": "🔌 Detached from the session. The next prompt starts a new one.",
    "no_sessions": "No sessions yet. Just send a prompt.",
    "rename_usage": "Usage: /rename <new title>",
    "no_session_rename": "No session to rename.",
    "renamed": "✅ Renamed: {title}",
    "model_format": "Format: /model providerID/modelID",
    "model_set": "✅ Model set: {model}",
    "model_current": "Current model: {model}\nSet: /model providerID/modelID",
    "agent_set": "✅ Agent set: {agent}",
    "no_agents": "No agents available. Set: /agent <name>",
    "pick_number": "_Reply with the number._",
    "nothing_to_pick": "Nothing to choose.",
    "title_sessions": "🗂 Sessions:",
    "title_models": "🧠 Models:",
    "title_agents": "🎭 Agents:",
    "title_projects": "📁 Projects:",
    "title_worktrees": "🌿 Worktrees:",
    "title_commands": "⚡ Commands:",
    "title_skills": "🧩 Skills:",
    "title_mcps": "🔌 MCP servers:",
    "title_messages": "💬 Messages:",
    "title_action": "Action:",
    "no_projects": "No projects found.",
    "no_worktrees": "No worktrees found.",
    "no_commands": "No commands available.",
    "no_skills": "No skills available.",
    "no_mcps": "No MCP servers configured.",
    "no_messages": "No messages.",
    "dir_switched": "✅ {kind} switched: {directory}\nNew session on the next prompt.",
    "reverted": "↩️ Reverted.",
    "mcp_toggled": "🔌 {name} {state}.",
    "mcp_on": "enabled",
    "mcp_off": "disabled",
    "action_revert": "↩️ Revert (back to here)",
    "action_fork": "🍴 Fork (new session from here)",
    "perm_once": "🔐 allowed (once).",
    "perm_always": "🔐 allowed (always).",
    "perm_reject": "🔐 rejected.",
    "answered": "✅ {answer}",
    "tts_unconfigured": "TTS is not configured (TTS_API_URL / TTS_API_KEY).",
    "tts_on": "🔊 Spoken replies enabled.",
    "tts_off": "🔊 Spoken replies disabled.",
    "no_scheduler": "Scheduled tasks are not enabled.",
    "task_usage": "Usage: /task <minutes> <prompt>  or  /task every <minutes> <prompt>",
    "task_limit": "Limit reached ({limit} tasks). Delete one first (/tasklist).",
    "task_created": "⏰ Task scheduled (in {minutes} min).",
    "task_none": "No scheduled tasks.",
    "task_deleted": "🗑 Task deleted.",
    "title_tasks": "⏰ Scheduled tasks:",
    "status": "📊 OpenCode: {health}\nSession: {sid}\nModel: {model}\nAgent: {agent}",
    "reachable": "✅ reachable",
    "unreachable": "⚠️ unreachable",
    "help": (
        "🤖 *opencode-talk-bridge*\n"
        "Send a message to prompt OpenCode. Commands:\n"
        "• /new — start a fresh OpenCode session\n"
        "• /session — show the current session id\n"
        "• /sessions — list & switch recent sessions\n"
        "• /rename <title> — rename the current session\n"
        "• /detach — detach from the current session\n"
        "• /messages — browse messages, then revert or fork\n"
        "• /model [providerID/modelID] — show, pick, or set the model\n"
        "• /agent [name] — show, pick, or set the agent (plan/build)\n"
        "• /projects — switch the OpenCode project\n"
        "• /worktree — switch the git worktree\n"
        "• /commands — browse & run custom OpenCode commands\n"
        "• /skills — browse & run OpenCode skills\n"
        "• /mcps — enable/disable MCP servers\n"
        "• /tts — toggle spoken replies (if configured)\n"
        "• /task <min> <prompt> — schedule a task (/task every <min> … to repeat)\n"
        "• /tasklist — list/delete scheduled tasks\n"
        "• /stop — abort the current run\n"
        "• /status — bridge & OpenCode health\n"
        "• /help — this message\n"
        "Pickers: reply with the number. Permission: `ja` (once), "
        "`immer` (always), `nein` (deny)."
    ),
}

CATALOG: dict[str, dict[str, str]] = {"de": DE, "en": EN}


def translator(locale: str) -> Callable[..., str]:
    table = CATALOG.get(locale, DE)

    def t(key: str, **fields: object) -> str:
        template = table.get(key) or DE.get(key, key)
        return template.format(**fields) if fields else template

    return t
