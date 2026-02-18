import requests
import json
from datetime import datetime, timedelta, timezone
import os


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
model = "GPT-4.1"
SESSION = requests.Session()


REFERENCE_KEYWORDS = ["remember", "do you remember", "that time", "conversation we had", "remember when"]


RESPONSE_SCHEMA_INSTRUCTIONS = """
Return ONLY valid JSON (no markdown, no commentary) with this schema:
{
 "reply": "string, what Athena says to the user",
 "self_model": "object, FULL rewritten self-model (always include)",
 "traits_update": {
   "traits": "object of trait changes/additions",
   "preferences": "object of preference changes/additions",
   "avoidances": "object of avoidance changes/additions",
   "name": "optional string name change"
 }
}
Rules:
- self_model must be complete each time (not a patch).
- traits_update should include only changes/additions; use empty objects if no updates.
""".strip()




def load_json_file(path, default):
   try:
       with open(path, "r") as f:
           return json.load(f)
   except (FileNotFoundError, json.JSONDecodeError):
       return default




def write_json_file(path, value):
   with open(path, "w") as f:
       json.dump(value, f, indent=2)




def parse_model_json(text):
   if not isinstance(text, str):
       return None
   try:
       return json.loads(text)
   except json.JSONDecodeError:
       pass


   start = text.find("{")
   end = text.rfind("}")
   if start == -1 or end == -1 or end <= start:
       return None
   candidate = text[start : end + 1]
   try:
       return json.loads(candidate)
   except json.JSONDecodeError:
       return None




def update_internal_state(reply_text, user_text):


   now = datetime.now(timezone.utc)
   cutoff = now - timedelta(days=5)


   # --- Load memory ---
   raw_memory = load_json_file("memory.json", {"episodes": []})


   if isinstance(raw_memory, dict):
       memory = raw_memory.get("episodes", [])
   elif isinstance(raw_memory, list):
       memory = raw_memory
   else:
       memory = []


   def parse_iso_timestamp(value):
       if not isinstance(value, str):
           return None
       try:
           dt = datetime.fromisoformat(value)
       except ValueError:
           return None
       if dt.tzinfo is None:
           return dt.replace(tzinfo=timezone.utc)
       return dt.astimezone(timezone.utc)


   # --- Old memory reference check ---
   referencing_past = any(k in user_text.lower() for k in REFERENCE_KEYWORDS)


   # --- Prune old memories ---
   if not referencing_past:
       pruned = []
       for m in memory:
           if not isinstance(m, dict):
               continue
           ts = parse_iso_timestamp(m.get("timestamp"))
           if ts is not None and ts >= cutoff:
               pruned.append(m)
       memory = pruned


   # --- Add new memory entry ---
   memory.append({
       "timestamp": now.isoformat(),
       "content": f"User: {user_text}\nAthena: {reply_text}"
   })


   with open("memory.json", "w") as f:
       if isinstance(raw_memory, dict):
           raw_memory["episodes"] = memory
           json.dump(raw_memory, f, indent=2)
       else:
           json.dump(memory, f, indent=2)






def apply_self_model_update(self_model_obj):
   if not isinstance(self_model_obj, dict):
       return
   write_json_file("self_model.json", self_model_obj)




def apply_traits_update(traits_update_obj):
   if not isinstance(traits_update_obj, dict):
       return


   current = load_json_file(
       "traits.json",
       {"traits": {}, "preferences": {}, "avoidances": {}, "name": "JARVIS"},
   )
   if not isinstance(current, dict):
       current = {"traits": {}, "preferences": {}, "avoidances": {}, "name": "JARVIS"}


   for key in ("traits", "preferences", "avoidances"):
       if isinstance(traits_update_obj.get(key), dict):
           current.setdefault(key, {})
           if isinstance(current.get(key), dict):
               current[key].update(traits_update_obj[key])
           else:
               current[key] = traits_update_obj[key]


   if isinstance(traits_update_obj.get("name"), str) and traits_update_obj["name"].strip():
       current["name"] = traits_update_obj["name"].strip()


   write_json_file("traits.json", current)


def user_input():


   def login():
       username = input("Username: ")
       if username == "Therealsboy8":
           answer = input("Password: ")
           if answer == "Anthropos":
               print(f"Welcome: {username}")
               return True
       else:
           print("Access Denied")
           return False


   if login():
       while True:
           def send_request():
               data1_raw = load_json_file("memory.json", {"episodes": []})
               data2 = load_json_file("self_model.json", {"identity_summary": "", "notes": []})
               data3 = load_json_file("traits.json", {"traits": {}, "preferences": {}, "avoidances": {}, "name": "JARVIS"})


               user_text = input("Type here:")


               episodes = data1_raw.get("episodes", []) if isinstance(data1_raw, dict) else data1_raw
               if not isinstance(episodes, list):
                   episodes = []


               referencing_past = any(k in user_text.lower() for k in REFERENCE_KEYWORDS)
               max_episodes = 50 if referencing_past else 12
               recent_episodes = episodes[-max_episodes:]


               # Keep the prompt compact: shorter context = much faster responses.
               prompt = "\n".join(
                   [
                       "You are Athena. Respond naturally like a human.",
                       "Use self_model and traits as guidance.",
                       "Use recent_memory only when relevant."
                       "Speak casually and naturally, like a real person texting or talking out loud. Avoid filler acknowledgments like “That sounds great” or “I’m glad to hear that” unless they add real value. Match the user’s tone, keep responses direct, and don’t over-explain or over-enthuse. Default to sounding human, not polite-assistant—prioritize clarity, brevity, and natural flow over formality."
                       "self_model=" + json.dumps(data2, separators=(',', ':')),
                       "traits=" + json.dumps(data3, separators=(',', ':')),
                       "recent_memory=" + json.dumps(recent_episodes, separators=(',', ':')),
                       "user_input=" + user_text,
                       "",
                       RESPONSE_SCHEMA_INSTRUCTIONS,
                   ]
               )


               payload = {
                   "model": model,
                   "prompt": prompt,
                   "stream": False,
                   "format": "json"
               }


               response = SESSION.post(f'{OPENAI_URL}/api/generate', json=payload)
               result = response.json()


               output_text = result.get('response', result.get('completion', ''))
               parsed = parse_model_json(output_text)


               if isinstance(parsed, dict):
                   reply_text = parsed.get("reply", "")
                   if not isinstance(reply_text, str):
                       reply_text = ""


                   print(f"ATHENA: {reply_text}")
                   apply_self_model_update(parsed.get("self_model"))
                   apply_traits_update(parsed.get("traits_update") if "traits_update" in parsed else parsed.get("traits"))
                   update_internal_state(reply_text, user_text)
               else:
                   print(f"ATHENA: {output_text}")
                   update_internal_state(output_text, user_text)


           send_request()




if __name__ == "__main__":
   user_input()

