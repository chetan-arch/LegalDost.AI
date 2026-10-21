"""User-facing strings. Kannada strings are draft translations that need native-speaker review."""

from __future__ import annotations

from typing import Any

STRINGS: dict[str, dict[str, str]] = {
    "notice": {
        "en": "Namaste! I'm LegalDost, an automated legal *information* assistant. I am not a lawyer, court, "
        "police or government service, and I can't guarantee outcomes. Please don't share ID numbers, "
        "bank details or passwords. Messages are kept for {hours} hours; send DELETE MY DATA anytime.",
        "kn": "ನಮಸ್ಕಾರ! ನಾನು LegalDost, ಸ್ವಯಂಚಾಲಿತ ಕಾನೂನು *ಮಾಹಿತಿ* ಸಹಾಯಕ. ನಾನು ವಕೀಲ, ನ್ಯಾಯಾಲಯ, ಪೊಲೀಸ್ "
        "ಅಥವಾ ಸರ್ಕಾರಿ ಸೇವೆ ಅಲ್ಲ, ಮತ್ತು ಫಲಿತಾಂಶವನ್ನು ಖಾತರಿಪಡಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ಗುರುತಿನ ಸಂಖ್ಯೆ, ಬ್ಯಾಂಕ್ "
        "ವಿವರಗಳು ಅಥವಾ ಪಾಸ್‌ವರ್ಡ್ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ. ಸಂದೇಶಗಳನ್ನು {hours} ಗಂಟೆಗಳ ಕಾಲ ಇಡಲಾಗುತ್ತದೆ; ಯಾವಾಗ ಬೇಕಾದರೂ "
        "DELETE MY DATA ಎಂದು ಕಳುಹಿಸಿ.",
    },
    "help": {
        "en": "I'm *LegalDost*. I explain Indian law in simple words using official legal texts: what the law "
        "says, how it may apply to you, and safe next steps.\n\n"
        "*I can answer questions about:* {coverage}.\n\n"
        "*Try asking:*\n"
        "• What is the fine for not wearing a helmet?\n"
        "• What is the fine for not wearing a seat belt?\n"
        "• Can police fine me for tinted car windows?\n"
        "• Can a shop refuse to refund a defective product?\n\n"
        "*Tips:* tell me which state you're in and roughly when it happened. Reply *MORE* for details, "
        "*SOURCES* for the exact legal text, *RESET* to start over, *DELETE MY DATA* to erase this chat.\n\n"
        "I'm not a lawyer. For serious matters I'll point you to free legal aid.",
        "kn": "ನಿಮ್ಮ ಪರಿಸ್ಥಿತಿಯನ್ನು ನಿಮ್ಮದೇ ಮಾತಿನಲ್ಲಿ ವಿವರಿಸಿ. ಬೇಕಾದ ಮಾಹಿತಿಯನ್ನು ಕೇಳಿ, ನೋಂದಾಯಿತ ಕಾನೂನು "
        "ಮೂಲಗಳಿಂದ ಉತ್ತರಿಸುತ್ತೇನೆ.\nವಿವರಕ್ಕೆ *MORE*, ಸಾಕ್ಷ್ಯಕ್ಕೆ *SOURCES*, ಭಾಷೆ ಬದಲಿಸಲು *KANNADA* / *ENGLISH*, "
        "ಮರುಪ್ರಾರಂಭಿಸಲು *RESET*, ಅಳಿಸಲು *DELETE MY DATA* ಕಳುಹಿಸಿ.\nಈಗ ಪರಿಶೀಲಿತ ವ್ಯಾಪ್ತಿ: {coverage}.",
    },
    "clarify_intro": {
        "en": "To answer this accurately I need a little more information:",
        "kn": "ಇದಕ್ಕೆ ನಿಖರವಾಗಿ ಉತ್ತರಿಸಲು ನನಗೆ ಇನ್ನಷ್ಟು ಮಾಹಿತಿ ಬೇಕು:",
    },
    "clarify_why": {
        "en": "(The answer can change depending on this, so I won't assume it.)",
        "kn": "(ಉತ್ತರ ಇದರ ಮೇಲೆ ಬದಲಾಗಬಹುದು, ಆದ್ದರಿಂದ ನಾನು ಊಹಿಸುವುದಿಲ್ಲ.)",
    },
    "unsupported_domain": {
        "en": "I can't give a verified answer about {domain} yet: no authoritative sources for it are loaded "
        "in my database. My verified coverage right now is: {coverage}. For this issue, a lawyer or your "
        "District Legal Services Authority can help.",
        "kn": "{domain} ಬಗ್ಗೆ ಪರಿಶೀಲಿತ ಉತ್ತರ ನೀಡಲು ಇನ್ನೂ ಸಾಧ್ಯವಿಲ್ಲ: ಅದಕ್ಕೆ ಅಧಿಕೃತ ಮೂಲಗಳು ನನ್ನ ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ "
        "ಇಲ್ಲ. ಈಗ ಪರಿಶೀಲಿತ ವ್ಯಾಪ್ತಿ: {coverage}. ಈ ವಿಷಯಕ್ಕೆ ವಕೀಲರು ಅಥವಾ ಜಿಲ್ಲಾ ಕಾನೂನು ಸೇವೆಗಳ ಪ್ರಾಧಿಕಾರ ಸಹಾಯ ಮಾಡಬಹುದು.",
    },
    "unknown_topic": {
        "en": "I'm not sure which legal area this is about. Could you describe what happened, where (which "
        "state), and what you want to know?",
        "kn": "ಇದು ಯಾವ ಕಾನೂನು ವಿಷಯಕ್ಕೆ ಸಂಬಂಧಿಸಿದೆ ಎಂದು ನನಗೆ ಖಚಿತವಿಲ್ಲ. ಏನಾಯಿತು, ಎಲ್ಲಿ (ಯಾವ ರಾಜ್ಯ), ಮತ್ತು ನೀವು "
        "ಏನು ತಿಳಿಯಲು ಬಯಸುತ್ತೀರಿ ಎಂದು ವಿವರಿಸಬಹುದೇ?",
    },
    "no_evidence": {
        "en": "I don't have an official legal source loaded that answers this yet, so I can't give you a verified "
        "answer and I won't guess. (Area: {what}.) A lawyer or your District Legal Services Authority can help "
        "with this one. Reply HELP to see what I can answer.",
        "kn": "ಇದಕ್ಕೆ ಸಂಬಂಧಿಸಿದ ನೋಂದಾಯಿತ ಕಾನೂನು ಮೂಲ ನನಗೆ ಸಿಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಉತ್ತರವನ್ನು ಪರಿಶೀಲಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ "
        "ಮತ್ತು ನಾನು ಊಹಿಸುವುದಿಲ್ಲ. ಕೊರತೆ: {what} ಕುರಿತ ಅಧಿಕೃತ ಮೂಲ.",
    },
    "emergency": {
        "en": "If you or someone else is in immediate danger, call *{phone}* (national emergency number) now. "
        "Move to a safe, public place if you can. Legal questions can wait until you are safe; message me "
        "afterwards and I'll help.",
        "kn": "ನೀವು ಅಥವಾ ಬೇರೆಯವರು ತಕ್ಷಣದ ಅಪಾಯದಲ್ಲಿದ್ದರೆ, ಈಗಲೇ *{phone}* (ರಾಷ್ಟ್ರೀಯ ತುರ್ತು ಸಂಖ್ಯೆ) ಗೆ ಕರೆ ಮಾಡಿ. "
        "ಸಾಧ್ಯವಾದರೆ ಸುರಕ್ಷಿತ, ಸಾರ್ವಜನಿಕ ಸ್ಥಳಕ್ಕೆ ಹೋಗಿ. ನೀವು ಸುರಕ್ಷಿತರಾದ ನಂತರ ನನಗೆ ಸಂದೇಶ ಕಳುಹಿಸಿ.",
    },
    "prohibited": {
        "en": "I can't help with that. Offering bribes, evading or obstructing officers, or hiding or altering "
        "evidence or documents can create serious legal problems for you. I can help you understand what "
        "the law says and the legitimate ways to respond to or challenge a decision.",
        "kn": "ಅದಕ್ಕೆ ನಾನು ಸಹಾಯ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ. ಲಂಚ ನೀಡುವುದು, ಅಧಿಕಾರಿಗಳನ್ನು ತಪ್ಪಿಸುವುದು ಅಥವಾ ಅಡ್ಡಿಪಡಿಸುವುದು, "
        "ಅಥವಾ ಸಾಕ್ಷ್ಯ/ದಾಖಲೆಗಳನ್ನು ಮರೆಮಾಡುವುದು ನಿಮಗೆ ಗಂಭೀರ ಕಾನೂನು ತೊಂದರೆ ತರಬಹುದು. ಕಾನೂನು ಏನು ಹೇಳುತ್ತದೆ ಮತ್ತು "
        "ನಿರ್ಧಾರವನ್ನು ಪ್ರಶ್ನಿಸುವ ಕಾನೂನುಬದ್ಧ ಮಾರ್ಗಗಳನ್ನು ತಿಳಿಯಲು ನಾನು ಸಹಾಯ ಮಾಡಬಲ್ಲೆ.",
    },
    "liberty_note": {
        "en": "This may affect your liberty or involve a criminal process. Please speak to a lawyer as soon as "
        "possible. Free legal aid: {legal_aid}.",
        "kn": "ಇದು ನಿಮ್ಮ ಸ್ವಾತಂತ್ರ್ಯದ ಮೇಲೆ ಪರಿಣಾಮ ಬೀರಬಹುದು ಅಥವಾ ಕ್ರಿಮಿನಲ್ ಪ್ರಕ್ರಿಯೆಯನ್ನು ಒಳಗೊಂಡಿರಬಹುದು. "
        "ಸಾಧ್ಯವಾದಷ್ಟು ಬೇಗ ವಕೀಲರೊಂದಿಗೆ ಮಾತನಾಡಿ. ಉಚಿತ ಕಾನೂನು ನೆರವು: {legal_aid}.",
    },
    "deadline_note": {
        "en": "There may be a deadline or a serious consequence here. Please have a lawyer review the documents "
        "before the date. Free legal aid: {legal_aid}.",
        "kn": "ಇಲ್ಲಿ ಗಡುವು ಅಥವಾ ಗಂಭೀರ ಪರಿಣಾಮ ಇರಬಹುದು. ದಿನಾಂಕದ ಮೊದಲು ವಕೀಲರಿಂದ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ. "
        "ಉಚಿತ ಕಾನೂನು ನೆರವು: {legal_aid}.",
    },
    "traffic_fine_note": {
        "en": "Amounts in the Act can differ from what is collected on the spot: states can notify their own "
        "compounding amounts, and Karnataka's current notification is not loaded here. Check the amount "
        "printed on your challan and pay only through official channels.",
    },
    "h_tldr": {"en": "In short", "kn": "ಸಂಕ್ಷಿಪ್ತವಾಗಿ"},
    "h_law_simple": {"en": "What the law says (in simple words)", "kn": "ಕಾನೂನು ಏನು ಹೇಳುತ್ತದೆ (ಸರಳವಾಗಿ)"},
    "ai_summary_note": {
        "en": "This summary was written automatically from the sources listed. Reply SOURCES to read the exact text.",
        "kn": "ಈ ಸಾರಾಂಶವನ್ನು ಪಟ್ಟಿ ಮಾಡಿದ ಮೂಲಗಳಿಂದ ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಬರೆಯಲಾಗಿದೆ. ನಿಖರ ಪಠ್ಯ ಓದಲು SOURCES ಎಂದು ಉತ್ತರಿಸಿ.",
    },
    "h_sources": {"en": "Sources", "kn": "ಮೂಲಗಳು"},
    "h_exceptions": {"en": "Limits and exceptions", "kn": "ಮಿತಿಗಳು ಮತ್ತು ವಿನಾಯಿತಿಗಳು"},
    "h_missing": {"en": "Still unknown", "kn": "ಇನ್ನೂ ತಿಳಿದಿಲ್ಲ"},
    "h_next": {"en": "Safe next steps", "kn": "ಸುರಕ್ಷಿತ ಮುಂದಿನ ಹೆಜ್ಜೆಗಳು"},
    "h_apply": {"en": "How it may apply to you", "kn": "ಇದು ನಿಮಗೆ ಹೇಗೆ ಅನ್ವಯಿಸಬಹುದು"},
    "h_law": {"en": "What the sources say", "kn": "ಮೂಲಗಳು ಏನು ಹೇಳುತ್ತವೆ"},
    "h_assumptions": {"en": "Assumptions", "kn": "ಊಹೆಗಳು"},
    "h_evidence": {"en": "Evidence", "kn": "ಸಾಕ್ಷ್ಯ"},
    "footer_quick": {
        "en": "Reply *MORE* for the full explanation or *SOURCES* for the exact text.",
        "kn": "ಪೂರ್ಣ ವಿವರಣೆಗೆ *MORE* ಅಥವಾ ನಿಖರ ಪಠ್ಯಕ್ಕೆ *SOURCES* ಎಂದು ಉತ್ತರಿಸಿ.",
    },
    "disclaimer": {
        "en": "_Legal information, not legal advice. Citations are checked mechanically against stored sources; "
        "that does not prove the interpretation is correct._",
        "kn": "_ಇದು ಕಾನೂನು ಮಾಹಿತಿ, ಕಾನೂನು ಸಲಹೆ ಅಲ್ಲ. ಉಲ್ಲೇಖಗಳನ್ನು ಸಂಗ್ರಹಿತ ಮೂಲಗಳೊಂದಿಗೆ ಯಾಂತ್ರಿಕವಾಗಿ "
        "ಪರಿಶೀಲಿಸಲಾಗಿದೆ; ಅದು ವ್ಯಾಖ್ಯಾನ ಸರಿಯೆಂದು ಸಾಬೀತುಪಡಿಸುವುದಿಲ್ಲ._",
    },
    "extractive_summary": {
        "en": "I found legal text that looks relevant, but I can't summarise it automatically right now. "
        "Here is exactly what it says (not a conclusion about your case).",
        "kn": "ಸಂಬಂಧಿಸಿದಂತೆ ತೋರುವ ಕಾನೂನು ಪಠ್ಯ ಸಿಕ್ಕಿದೆ, ಆದರೆ ಈಗ ಅದನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಸಾರಾಂಶ ಮಾಡಲು ಆಗುತ್ತಿಲ್ಲ. "
        "ಅದು ನಿಖರವಾಗಿ ಏನು ಹೇಳುತ್ತದೆ ಎಂಬುದು ಇಲ್ಲಿದೆ (ನಿಮ್ಮ ಪ್ರಕರಣದ ಬಗ್ಗೆ ತೀರ್ಮಾನವಲ್ಲ).",
    },
    "extractive_position": {
        "en": "Not determined: interpretation requires review of the quoted text (or an advocate).",
        "kn": "ನಿರ್ಧರಿಸಲಾಗಿಲ್ಲ: ಉಲ್ಲೇಖಿತ ಪಠ್ಯದ ಪರಿಶೀಲನೆ (ಅಥವಾ ವಕೀಲರು) ಅಗತ್ಯ.",
    },
    "extractive_claim": {"en": "{title}, {locator}, states:", "kn": "{title}, {locator}, ಹೀಗೆ ಹೇಳುತ್ತದೆ:"},
    "next_check_sources": {
        "en": "Read the quoted source text yourself, and keep every notice, receipt, bill, agreement or message related to this.",
        "kn": "ಉಲ್ಲೇಖಿತ ಮೂಲ ಪಠ್ಯವನ್ನು ನೀವೇ ಓದಿ, ಮತ್ತು ಇದಕ್ಕೆ ಸಂಬಂಧಿಸಿದ ಎಲ್ಲ ನೋಟಿಸ್, ರಸೀದಿ, ಬಿಲ್, ಒಪ್ಪಂದ ಅಥವಾ ಸಂದೇಶಗಳನ್ನು ಇಟ್ಟುಕೊಳ್ಳಿ.",
    },
    "next_stay_calm": {
        "en": "If you are dealing with an officer now, stay calm and polite, ask which provision applies and "
        "ask for a written challan or receipt for any fine.",
        "kn": "ನೀವು ಈಗ ಅಧಿಕಾರಿಯೊಂದಿಗೆ ವ್ಯವಹರಿಸುತ್ತಿದ್ದರೆ, ಶಾಂತ ಮತ್ತು ವಿನಯದಿಂದಿರಿ, ಯಾವ ನಿಯಮ ಅನ್ವಯಿಸುತ್ತದೆ ಎಂದು "
        "ಕೇಳಿ ಮತ್ತು ಯಾವುದೇ ದಂಡಕ್ಕೆ ಲಿಖಿತ ಚಲನ್ ಅಥವಾ ರಸೀದಿ ಕೇಳಿ.",
    },
    "next_advocate": {
        "en": "If the amount or consequence is significant, ask a lawyer or the free legal aid service to review it.",
        "kn": "ಮೊತ್ತ ಅಥವಾ ಪರಿಣಾಮ ಗಮನಾರ್ಹವಾಗಿದ್ದರೆ, ವಕೀಲರು ಅಥವಾ ಉಚಿತ ಕಾನೂನು ನೆರವು ಸೇವೆಯಿಂದ ಪರಿಶೀಲಿಸಿ.",
    },
    "assume_current": {
        "en": "I used the sources as currently registered. If this happened on an earlier date, tell me the date "
        "because the rules may have been different.",
        "kn": "ಈಗ ನೋಂದಾಯಿತವಾಗಿರುವ ಮೂಲಗಳನ್ನು ಬಳಸಿದ್ದೇನೆ. ಇದು ಹಿಂದಿನ ದಿನಾಂಕದಲ್ಲಿ ನಡೆದಿದ್ದರೆ, ದಿನಾಂಕ ತಿಳಿಸಿ; ಆಗ ನಿಯಮಗಳು ಬೇರೆಯಾಗಿರಬಹುದು.",
    },
    "persuasive_note": {
        "en": "Decision of another state's High Court: not binding in {state}, but may be persuasive.",
        "kn": "ಬೇರೆ ರಾಜ್ಯದ ಹೈಕೋರ್ಟ್ ತೀರ್ಪು: {state} ನಲ್ಲಿ ಬದ್ಧವಲ್ಲ, ಆದರೆ ಮಾರ್ಗದರ್ಶಕವಾಗಿರಬಹುದು.",
    },
    "deleted": {
        "en": "Done. Your conversation data on this service has been deleted.",
        "kn": "ಆಯಿತು. ಈ ಸೇವೆಯಲ್ಲಿನ ನಿಮ್ಮ ಸಂಭಾಷಣೆಯ ಡೇಟಾವನ್ನು ಅಳಿಸಲಾಗಿದೆ.",
    },
    "reset": {
        "en": "Okay, starting fresh. What would you like to ask?",
        "kn": "ಸರಿ, ಹೊಸದಾಗಿ ಪ್ರಾರಂಭಿಸೋಣ. ನೀವು ಏನು ಕೇಳಲು ಬಯಸುತ್ತೀರಿ?",
    },
    "english_only": {
        "en": "Sorry, I can only reply in English for now. Please type your question in English.",
    },
    "language_set": {"en": "I'll reply in English from now on.", "kn": "ಇನ್ನು ಮುಂದೆ ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸುತ್ತೇನೆ."},
    "no_previous": {
        "en": "There's no earlier answer to expand yet. Please ask your question first.",
        "kn": "ವಿಸ್ತರಿಸಲು ಹಿಂದಿನ ಉತ್ತರ ಇಲ್ಲ. ಮೊದಲು ನಿಮ್ಮ ಪ್ರಶ್ನೆ ಕೇಳಿ.",
    },
    "rate_limited": {
        "en": "You've sent many messages in a short time. Please wait a while and try again.",
        "kn": "ಕಡಿಮೆ ಸಮಯದಲ್ಲಿ ಹಲವು ಸಂದೇಶಗಳು ಬಂದಿವೆ. ಸ್ವಲ್ಪ ಸಮಯ ಕಾಯ್ದು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "media_unsupported": {
        "en": "I can't read {kind} messages yet. Please type the key details (for example, the section or rule "
        "written on the challan).",
        "kn": "ನಾನು ಇನ್ನೂ {kind} ಸಂದೇಶಗಳನ್ನು ಓದಲಾರೆ. ದಯವಿಟ್ಟು ಮುಖ್ಯ ವಿವರಗಳನ್ನು ಟೈಪ್ ಮಾಡಿ (ಉದಾ: ಚಲನ್‌ನಲ್ಲಿ ಬರೆದ ಸೆಕ್ಷನ್ ಅಥವಾ ನಿಯಮ).",
    },
    "too_long": {
        "en": "That message is too long for me. Please send a shorter description (under {limit} characters).",
        "kn": "ಆ ಸಂದೇಶ ತುಂಬಾ ಉದ್ದವಾಗಿದೆ. ದಯವಿಟ್ಟು {limit} ಅಕ್ಷರಗಳ ಒಳಗೆ ಕಳುಹಿಸಿ.",
    },
    "error": {
        "en": "Sorry, something went wrong on my side and I couldn't check the sources. Please try again shortly.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನ್ನ ಕಡೆ ತೊಂದರೆಯಾಗಿದೆ ಮತ್ತು ಮೂಲಗಳನ್ನು ಪರಿಶೀಲಿಸಲು ಆಗಲಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "kn_quotes_english": {
        "en": "",
        "kn": "(ಮೂಲ ಪಠ್ಯ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿದೆ; ಅಧಿಕೃತ ಕನ್ನಡ ಅನುವಾದ ನೋಂದಾಯಿಸಲಾಗಿಲ್ಲ.)",
    },
    "status_sufficient": {"en": "Supported by registered sources", "kn": "ನೋಂದಾಯಿತ ಮೂಲಗಳಿಂದ ಬೆಂಬಲಿತ"},
    "status_partially_supported": {
        "en": "Partly supported: important facts or sources are missing",
        "kn": "ಭಾಗಶಃ ಬೆಂಬಲಿತ: ಮುಖ್ಯ ಮಾಹಿತಿ ಅಥವಾ ಮೂಲಗಳು ಕೊರತೆ",
    },
    "status_conflicting": {"en": "Sources conflict", "kn": "ಮೂಲಗಳು ಪರಸ್ಪರ ವಿರುದ್ಧವಾಗಿವೆ"},
    "status_no_reliable_evidence": {"en": "No reliable source found", "kn": "ವಿಶ್ವಾಸಾರ್ಹ ಮೂಲ ಸಿಗಲಿಲ್ಲ"},
    "status_human_review_recommended": {"en": "Lawyer review recommended", "kn": "ವಕೀಲರ ಪರಿಶೀಲನೆ ಶಿಫಾರಸು"},
    "label_status": {"en": "Evidence", "kn": "ಸಾಕ್ಷ್ಯ ಸ್ಥಿತಿ"},
    "cat_primary_official": {"en": "Official primary source", "kn": "ಅಧಿಕೃತ ಮೂಲ ದಾಖಲೆ"},
    "cat_official_secondary": {
        "en": "Official summary (not the law itself)",
        "kn": "ಅಧಿಕೃತ ಸಾರಾಂಶ (ಕಾನೂನು ಪಠ್ಯವಲ್ಲ)",
    },
    "cat_secondary": {"en": "Secondary copy/commentary", "kn": "ದ್ವಿತೀಯ ಪ್ರತಿ/ವ್ಯಾಖ್ಯಾನ"},
    "unverified_source": {
        "en": "metadata not yet reviewed by an advocate",
        "kn": "ಮೆಟಾಡೇಟಾ ಇನ್ನೂ ವಕೀಲರಿಂದ ಪರಿಶೀಲಿಸಲಾಗಿಲ್ಲ",
    },
    "status_unknown": {"en": "legal status: unknown", "kn": "ಕಾನೂನು ಸ್ಥಿತಿ: ತಿಳಿದಿಲ್ಲ"},
    # --- evidence-status reasons (pipeline/status.py) ---
    "r_no_claims": {
        "en": "no statement could be supported by a registered source",
        "kn": "ಯಾವುದೇ ಹೇಳಿಕೆಗೆ ನೋಂದಾಯಿತ ಮೂಲದ ಬೆಂಬಲ ಸಿಗಲಿಲ್ಲ",
    },
    "r_missing_facts": {"en": "material facts are missing: {facts}", "kn": "ಮುಖ್ಯ ಮಾಹಿತಿ ಕೊರತೆ: {facts}"},
    "r_no_primary": {
        "en": "no official primary source (Act, rules, Gazette notification or official court copy) is cited",
        "kn": "ಯಾವುದೇ ಅಧಿಕೃತ ಮೂಲ ದಾಖಲೆ (ಕಾಯ್ದೆ, ನಿಯಮ, ಗೆಜೆಟ್ ಅಧಿಸೂಚನೆ ಅಥವಾ ನ್ಯಾಯಾಲಯದ ಅಧಿಕೃತ ಪ್ರತಿ) ಉಲ್ಲೇಖಿಸಲಾಗಿಲ್ಲ",
    },
    "r_status_unknown": {
        "en": "whether the cited primary source is current law has not been verified",
        "kn": "ಉಲ್ಲೇಖಿತ ಮೂಲ ದಾಖಲೆ ಪ್ರಸ್ತುತ ಜಾರಿಯಲ್ಲಿರುವ ಕಾನೂನೇ ಎಂದು ಪರಿಶೀಲಿಸಲಾಗಿಲ್ಲ",
    },
    "r_unreviewed": {
        "en": "the cited sources have not yet been reviewed by an advocate",
        "kn": "ಉಲ್ಲೇಖಿತ ಮೂಲಗಳನ್ನು ಇನ್ನೂ ವಕೀಲರು ಪರಿಶೀಲಿಸಿಲ್ಲ",
    },
    "r_not_binding": {
        "en": "only decisions of courts that are not binding in your state are cited",
        "kn": "ನಿಮ್ಮ ರಾಜ್ಯದಲ್ಲಿ ಬದ್ಧವಲ್ಲದ ನ್ಯಾಯಾಲಯಗಳ ತೀರ್ಪುಗಳನ್ನು ಮಾತ್ರ ಉಲ್ಲೇಖಿಸಲಾಗಿದೆ",
    },
    "r_extractive": {
        "en": "no interpretation was performed (quotes only)",
        "kn": "ಯಾವುದೇ ವ್ಯಾಖ್ಯಾನ ಮಾಡಲಾಗಿಲ್ಲ (ಉಲ್ಲೇಖಗಳು ಮಾತ್ರ)",
    },
    "r_dropped": {
        "en": "{n} draft statement(s) were removed because they failed citation checks",
        "kn": "ಉಲ್ಲೇಖ ಪರಿಶೀಲನೆಯಲ್ಲಿ ವಿಫಲವಾದ {n} ಕರಡು ಹೇಳಿಕೆ(ಗಳನ್ನು) ತೆಗೆದುಹಾಕಲಾಗಿದೆ",
    },
    "r_blocked": {
        "en": "the draft mentioned provisions or figures not found in the sources, so only quotes are shown",
        "kn": "ಕರಡಿನಲ್ಲಿ ಮೂಲಗಳಲ್ಲಿಲ್ಲದ ನಿಯಮಗಳು ಅಥವಾ ಅಂಕಿಗಳು ಇದ್ದುದರಿಂದ ಉಲ್ಲೇಖಗಳನ್ನು ಮಾತ್ರ ತೋರಿಸಲಾಗಿದೆ",
    },
    "r_conflict": {
        "en": "the cited sources point in different directions",
        "kn": "ಉಲ್ಲೇಖಿತ ಮೂಲಗಳು ಬೇರೆ ಬೇರೆ ದಿಕ್ಕಿನಲ್ಲಿವೆ",
    },
    "r_liberty": {
        "en": "the situation may affect personal liberty",
        "kn": "ಪರಿಸ್ಥಿತಿ ವೈಯಕ್ತಿಕ ಸ್ವಾತಂತ್ರ್ಯದ ಮೇಲೆ ಪರಿಣಾಮ ಬೀರಬಹುದು",
    },
    "r_deadline": {
        "en": "a deadline or serious consequence may be involved",
        "kn": "ಗಡುವು ಅಥವಾ ಗಂಭೀರ ಪರಿಣಾಮ ಇರಬಹುದು",
    },
    "r_no_jurisdiction": {"en": "the state/jurisdiction is not established", "kn": "ರಾಜ್ಯ/ವ್ಯಾಪ್ತಿ ಖಚಿತವಾಗಿಲ್ಲ"},
    "r_high_risk": {
        "en": "this kind of matter can have serious consequences; a lawyer should review your specific facts",
        "kn": "ಈ ರೀತಿಯ ವಿಷಯಕ್ಕೆ ಗಂಭೀರ ಪರಿಣಾಮಗಳಿರಬಹುದು; ನಿಮ್ಮ ನಿರ್ದಿಷ್ಟ ಸಂಗತಿಗಳನ್ನು ವಕೀಲರು ಪರಿಶೀಲಿಸಬೇಕು",
    },
    "serious_matter_note": {
        "en": "Matters like this can have serious consequences. Please have a lawyer look at your specific facts. "
        "Free legal aid: {legal_aid}.",
        "kn": "ಇಂತಹ ವಿಷಯಗಳಿಗೆ ಗಂಭೀರ ಪರಿಣಾಮಗಳಿರಬಹುದು. ದಯವಿಟ್ಟು ನಿಮ್ಮ ನಿರ್ದಿಷ್ಟ ಸಂಗತಿಗಳನ್ನು ವಕೀಲರಿಗೆ ತೋರಿಸಿ. "
        "ಉಚಿತ ಕಾನೂನು ನೆರವು: {legal_aid}.",
    },
    "coverage_none": {
        "en": "no legal sources are loaded yet",
        "kn": "ಇನ್ನೂ ಯಾವುದೇ ಕಾನೂನು ಮೂಲಗಳನ್ನು ಲೋಡ್ ಮಾಡಿಲ್ಲ",
    },
    "fact_jurisdiction": {"en": "state", "kn": "ರಾಜ್ಯ"},
    "fact_glazing_type": {"en": "factory glass or added film", "kn": "ಕಂಪನಿ ಗಾಜು ಅಥವಾ ನಂತರ ಹಾಕಿದ ಫಿಲ್ಮ್"},
    "fact_vlt_percent": {"en": "VLT percentage", "kn": "VLT ಶೇಕಡಾ"},
    "fact_challan_issued": {"en": "whether a challan was issued", "kn": "ಚಲನ್ ನೀಡಲಾಗಿದೆಯೇ"},
    "fact_cited_provision": {"en": "the provision written on the challan", "kn": "ಚಲನ್‌ನಲ್ಲಿ ಬರೆದ ನಿಯಮ"},
    "fact_incident_date": {"en": "date of the incident", "kn": "ಘಟನೆಯ ದಿನಾಂಕ"},
}


def t(key: str, language: str = "en", **kwargs: Any) -> str:
    entry = STRINGS[key]
    template = entry.get(language) or entry["en"]
    return template.format(**kwargs) if kwargs else template
