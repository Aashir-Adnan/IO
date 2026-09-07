# Rule: resource budget

The default ("light") profile must leave the laptop usable during normal work.
LocalBackend enforces: on-demand model loading (no preload), short Ollama
keep_alive, OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1, num_thread capped
at (physical cores - 2). The "quality" profile is opt-in and may make the machine
sluggish during a call.
