# Taste
- Prefers bulk "Fix All" execution - applying all suggested shrink/yagni/native cleanups in one batch rather than piecemeal approvals. Confidence: 0.93
- Prefers aggressive code shrinking and DRY consolidation - merging duplicated channel modules into a single dispatcher (notify.py), extracting shared base models (NotificationConfig/Credential), and centralizing duplicated pipelines into one helper (run_sync_batch). Confidence: 0.85
- Prefers stdlib-native solutions over heavy frameworks when sufficient - e.g., http.server ThreadingHTTPServer over FastAPI/Uvicorn for simple JSON APIs to reduce dependencies. Confidence: 0.82
- Prefers YAGNI and minimal representation - removing redundant dual notifications (finish+result → single result with finish gate), alias functions, and triple field encodings (size_bytes/size_human only). Confidence: 0.80
- Prefers Pydantic native serialization (model_dump(mode="json")/model_validate) over manual serialize/parse logic, with empty-string → None normalization. Confidence: 0.78
- Prefers Discord Bot API integration (bot_token + channel_id with Authorization: Bot header to discord.com/api/v10/channels/{channel_id}/messages) over webhook URLs for Discord notifications. Confidence: 0.82
