"""Social copy generation (title, hook, caption, description, hashtags, CTA).

Template mode needs no LLM; an optional local LLM (Ollama) can rewrite the copy.
Both only use facts present in the clip (transcript, detected keywords, game,
category, creator): nothing is invented.
"""
