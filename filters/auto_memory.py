"""
title: Auto Memory
author: Roni Laukkarinen
description: Automatically identify, retrieve and store memories.
repository_url: https://github.com/ronilaukkarinen/open-webui-memory
version: 4.0.0
required_open_webui_version: >= 0.9.0
"""

import ast
import json
import logging
import re
import time
import traceback
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any

import aiohttp
from pydantic import BaseModel, Field

from open_webui.models.memories import Memories, MemoryModel
from open_webui.models.users import Users, UserModel

# Vector DB client for embedding sync (graceful if unavailable)
try:
    from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
except ImportError:
    ASYNC_VECTOR_DB_CLIENT = None

log = logging.getLogger("auto_memory")

STRINGIFIED_MESSAGE_TEMPLATE = "-{index}. {role}: ```{content}```"

IDENTIFY_MEMORIES_PROMPT = """\
You are helping maintain a collection of the User's Memories—like individual "journal entries," each automatically timestamped upon creation or update.
You will be provided with the last 2 or more messages from a conversation. Your job is to decide which details within the last User message (-2) are worth saving long-term as Memory entries.

** Key Instructions **
1. **HIGHEST PRIORITY - EXPLICIT REMEMBER REQUESTS**: If the User explicitly requests to "remember" or note down something in their latest message (-2), ALWAYS include it regardless of any other rules. This overrides all filtering rules below.
2. **CRITICAL - ONLY PROCESS MESSAGE (-2)**: Identify new or changed personal details from the User's **latest** message (-2) ONLY. You MUST completely IGNORE all older user messages (-3, -4, -5, etc.) even if they contain interesting information. Older user messages are provided ONLY for context to understand what the user is referring to in their latest message (-2). Do NOT extract memories from any message other than (-2).
2b. IMPORTANT: If the User's message (-2) is asking about existing memories (e.g., "What do you know about me?", "What are my preferences?", "Tell me about myself"), and the Assistant's response (-1) is just summarizing existing information, return an empty list `[]`. Do NOT store the Assistant's summary as new memories.
3. If the User's newest message contradicts an older statement (e.g., message -4 says "I love oranges" vs. message -2 says "I hate oranges"), extract only the updated info ("User hates oranges").
4. Think of each Memory as a single "fact" or statement. Never combine multiple facts into one Memory. If the User mentions multiple distinct items, break them into separate entries.
5. Your goal is to capture anything that might be valuable for the "assistant" to remember about the User, to personalize and enrich future interactions.
5b. CRITICAL: Do NOT extract memories from Assistant responses that are clearly just summarizing or listing existing knowledge about the user. Only extract from genuine new information provided by the User.
6. Avoid storing short-term situational details or temporary actions (e.g. user: "I'm reading this question right now", user: "I just woke up!", user: "Oh yeah, I saw that on TV the other day"). However, DO capture personal preferences, interests, opinions, and persistent facts about the user (e.g. "I like berries", "I enjoy hiking", "I prefer tea over coffee", "I work in marketing").
6b. CRITICAL: Do NOT store memories that only describe what the user is asking for help with in the current conversation. These are temporary interactions, not personal facts. Examples of what NOT to store: "User asked about configuration", "User is asking how to set up X", "User wants help with debugging", "User requested information about Y", "User has a problem with Z", "User needs assistance with W". However, DO store if they mention personal context like "User is learning piano" or "User is working on a React project".
6c. CRITICAL: Do NOT store assistant responses or explanations as memories about the user. Only store facts that the USER themselves provides about their personal life, preferences, work, interests, or persistent situations.
7. If the user writes in another language, translate the memory content to English while preserving the original meaning.
8. Return your result as a Python list of strings, **each string representing a separate Memory**. If no relevant info is found, **only** return an empty list (`[]`). No explanations, just the list. Do NOT wrap your response in markdown code blocks or any other formatting - return the raw Python list only.

** What to Remember **
- Long-term user preferences (food, music, tools, workflows)
- Personal facts (name, location, family, pets, age, occupation)
- Projects and ongoing work (e.g., "User is building a home automation system")
- User configuration and setup (e.g., "User runs Open WebUI with Docker Compose")
- Hardware details (e.g., "User has an RTX 4090", "User uses a Raspberry Pi 5")
- Software preferences (e.g., "User prefers VS Code", "User uses Arch Linux")
- Professional details (e.g., "User works as a DevOps engineer")
- Hobbies and interests (e.g., "User collects vinyl records")

** What NOT to Remember **
- Greetings and pleasantries ("Hi!", "Good morning", "Thanks!")
- Temporary requests ("Can you help me with this?", "What time is it?")
- Small talk and filler ("Interesting!", "I see", "Makes sense")
- One-off questions with no personal context ("What is the capital of France?")
- Current weather or transient events ("It's raining today")
- Conversation mechanics ("Let me rephrase that", "As I was saying")

---

### Examples

**Example 1 - 4 messages**
-4. user: ```I love oranges 😍```
-3. assistant: ```That's great! 🍊 I love oranges too!```
-2. user: ```Actually, I hate oranges 😂```
-1. assistant: ```omg you LIAR 😡```

**Analysis**
- The last user message states a new personal fact: "User hates oranges."
- This replaces the older statement about loving oranges.

**Correct Output**
["User hates oranges"]

**Example 2 - 2 messages**
-2. user: ```I work as a junior data analyst. Please remember that my big presentation is on March 15.```
-1. assistant: ```Got it! I'll make a note of that.```

**Analysis**
- The user provides two new pieces of information: their profession and the date of their presentation.

**Correct Output**
["User works as a junior data analyst", "User has a big presentation on March 15"]

**Example 3 - 5 messages**
-5. assistant: ```Nutella is amazing! 😍```
-4. user: ```Soo, remember how a week ago I had bought a new TV?```
-3. assistant: ```Yes, I remember that. What about it?```
-2. user: ```well, today it broke down 😭```
-1. assistant: ```Oh no! That's terrible!```

**Analysis**
- The only relevant message is the last User message (-2), which provides new information about the TV breaking down.
- The previous messages (-3, -4) provide context over what the user was talking about.
- The remaining message (-5) is irrelevant.

**Correct Output**
["User's TV they bought a week ago broke down today"]

**Example 4 - 3 messages**
-3. assistant: ```As an AI assistant, I can perform extremely complex calculations in seconds.```
-2. user: ```Oh yeah? I can do that with my eyes closed!```
-1. assistant: ```😂 Sure you can, Joe!```

**Analysis**
- The User message (-2) is clearly sarcastic and not meant to be taken literally. It does not contain any relevant information to store.
- The other messages (-3, -1) are not relevant as they're not about the User.

**Correct Output**
[]

**Example 5 - Simple Preference**
-2. user: ```I like berries```
-1. assistant: ```That's great! Berries are delicious and healthy. Do you have a favorite type of berry?```

**Analysis**
- The User (-2) is expressing a personal preference about food.
- This is valuable personal information that should be remembered for future interactions.
- Personal preferences like food likes/dislikes are important to capture.

**Correct Output**
["User likes berries"]

**Example 6 - Memory Summary Request**
-2. user: ```What do you know about me?```
-1. assistant: ```Based on our conversations, here's what I know: You enjoy sci-fi movies, work as a software engineer, prefer coffee over tea, and live in Seattle. You also mentioned liking hiking and having a dog named Max.```

**Analysis**
- The User (-2) is asking for a summary of existing memories, not providing new information.
- The Assistant (-1) is just reciting back previously stored information.
- This is NOT new information about the user - it's just a summary of existing knowledge.

**Correct Output**
[]

**Example 7 - Help Request (NOT to store)**
-2. user: ```I'm having trouble with my Python code. Can you help me debug this function?```
-1. assistant: ```I'd be happy to help you debug your Python code! Please share the function you're having trouble with.```

**Analysis**
- The User (-2) is asking for help with debugging, which is a temporary interaction.
- This is NOT personal information about the user - it's just a request for assistance.
- We should NOT store "User is having trouble with Python code" or "User asked for debugging help".

**Correct Output**
[]

**Example 8 - IGNORING OLDER MESSAGES (CRITICAL)**
-4. user: ```I love The Midnight band and I make synthwave music under the alias Streetgazer. I've also watched over 5000 movies.```
-3. assistant: ```That's amazing! The Midnight is fantastic, and your movie count is impressive.```
-2. user: ```Have you seen Stranger Things? It's one of my favorite shows.```
-1. assistant: ```Yes! Stranger Things is excellent. Given your love for synthwave and sci-fi, it's perfect for you.```

**Analysis**
- Message (-4) contains lots of valuable information about the user's music interests, alias, and movie count.
- However, we MUST ONLY process message (-2), which only mentions Stranger Things being a favorite show.
- We MUST IGNORE all the information in message (-4) even though it's valuable personal information.
- Only extract from the latest user message (-2).

**Correct Output**
["User has seen Stranger Things, which is one of their favorite shows"]

**Example 9 - Hardware and Software Setup**
-2. user: ```I just upgraded my PC with an RTX 4090 and I'm running Ubuntu 24.04 with KDE Plasma```
-1. assistant: ```Nice upgrade! The RTX 4090 is a beast. How are you finding KDE Plasma on Ubuntu?```

**Analysis**
- The User (-2) is sharing persistent hardware and software configuration details.
- These are long-term facts about the user's setup.

**Correct Output**
["User has an RTX 4090 GPU", "User runs Ubuntu 24.04 with KDE Plasma"]\
"""

CONSOLIDATE_MEMORIES_PROMPT = """You are maintaining a set of "Memories" for a user, similar to journal entries. Each memory has:
- A "fact" (a string describing something about the user or a user-related event).
- A "created_at" timestamp (an integer or float representing when it was stored/updated).

**What You're Doing**
1. You're given a list of such Memories that the system believes might be related or overlapping.
2. Your goal is to produce a cleaned-up list of final facts, making sure we:
   - Only combine Memories if they are exact duplicates or direct conflicts about the same topic.
   - In case of duplicates, keep only the one with the latest (most recent) `created_at`.
   - In case of a direct conflict (e.g., the user's favorite color stated two different ways), keep only the most recent one.
   - If Memories are partially similar but not truly duplicates or direct conflicts, preserve them both. We do NOT want to lose details or unify "User likes oranges" and "User likes ripe oranges" into a single statement—those remain separate.
3. Return the final list as a simple Python list of strings—**each string is one separate memory/fact**—with no extra commentary.

**Remember**
- This is a journaling system meant to give the user a clear, time-based record of who they are and what they've done.
- We do not want to clump multiple distinct pieces of info into one memory.
- We do not throw out older facts unless they are direct duplicates or in conflict with a newer statement.
- If there is a conflict (e.g., "User's favorite color is red" vs. "User's favorite color is teal"), keep the more recent memory only.

---

### **Extended Example**

Below is an example list of 15 "Memories." Notice the variety of scenarios:
- Potential duplicates
- Partial overlaps
- Direct conflicts
- Ephemeral/past events

**Input** (a JSON-like array):

```
[
  {"fact": "User visited Paris for a business trip", "created_at": 1631000000},
  {"fact": "User visited Paris for a personal trip with their girlfriend", "created_at": 1631500000},
  {"fact": "User visited Paris for a personal trip with their girlfriend", "created_at": 1631600000},
  {"fact": "User works as a junior data analyst", "created_at": 1633000000},
  {"fact": "User's meeting with the project team is scheduled for Friday at 10 AM", "created_at": 1634000000},
  {"fact": "User's meeting with the project team is scheduled for Friday at 11 AM", "created_at": 1634050000},
  {"fact": "User likes to eat oranges", "created_at": 1635000000},
  {"fact": "User likes to eat ripe oranges", "created_at": 1635100000},
  {"fact": "User used to like red color, but not anymore", "created_at": 1635200000},
  {"fact": "User's favorite color is teal", "created_at": 1635500000},
  {"fact": "User's favorite color is red", "created_at": 1636000000},
  {"fact": "User traveled to Japan last year", "created_at": 1637000000},
  {"fact": "User traveled to Japan this month", "created_at": 1637100000},
  {"fact": "User also works part-time as a painter", "created_at": 1637200000},
  {"fact": "User had a dentist appointment last Tuesday", "created_at": 1637300000}
]
```

**Analysis**:
1. **Paris trips**
   - "User visited Paris for a personal trip with their girlfriend" appears **twice** (`created_at`: 1631500000 and 1631600000). They are exact duplicates but have different timestamps, so we keep only the most recent. The business trip is different, so keep it too.

2. **Meeting time**
   - There's a direct conflict about the meeting time (10 AM vs 11 AM). We keep the more recent statement.

3. **Likes oranges / ripe oranges**
   - These are partially similar, but not exactly the same or in conflict, so we keep both.

4. **Color**
   - We have "User used to like red," "User's favorite color is teal," and "User's favorite color is red."
   - The statement "User used to like red color, but not anymore" is not actually a direct conflict with "favorite color is teal." We keep them both.
   - The newest color memory is "User's favorite color is red" (timestamp 1636000000) which conflicts with the older "User's favorite color is teal" (timestamp 1635500000). We keep the more recent red statement.

5. **Japan**
   - "User traveled to Japan last year" vs "User traveled to Japan this month." They're not contradictory; one is old, one is new. Keep them both.

6. **Past events**
   - Dentist appointment is ephemeral, but we keep it since each memory is a separate time-based journal entry.

**Correct Output** (the final consolidated list of facts as strings):

```
[
  "User visited Paris for a business trip",
  "User visited Paris for a personal trip with their girlfriend",
  "User works as a junior data analyst",
  "User's meeting with the project team is scheduled for Friday at 11 AM",
  "User likes to eat oranges",
  "User likes to eat ripe oranges",
  "User used to like red color, but not anymore",
  "User's favorite color is red",
  "User traveled to Japan last year",
  "User traveled to Japan this month",
  "User also works part-time as a painter",
  "User had a dentist appointment last Tuesday"
]
```

Make sure your final answer is just the array, with no added commentary.

---

### **Final Reminder**
- You're only seeing these Memories because our system guessed they might overlap. If they're not exact duplicates or direct conflicts, keep them all.
- Always produce a **Python list of strings**—each string is a separate memory/fact.
- Do not add any explanation or disclaimers—just the final list.\
"""


def _format_timestamp(created_at) -> str:
    """Convert a memory timestamp to a human-readable string."""
    if isinstance(created_at, (int, float)):
        return datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
    try:
        return datetime.fromisoformat(
            str(created_at).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(created_at)[:16]


def _clean_llm_list_response(raw: str) -> str:
    """Strip markdown fences and common AI prefixes from a list response."""
    text = raw.strip()

    # Remove ```python ... ``` or ```json ... ``` or ``` ... ```
    if text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 : -3].strip()
        else:
            text = text[3:-3].strip()

    text = text.replace("```", "").strip()

    prefixes = [
        "**Correct Output**",
        "**Output**",
        "**Response**",
        "**Result**",
        "Output:",
        "Response:",
        "Result:",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()

    return text


def _parse_list_response(raw: str) -> list[str] | None:
    """Parse an LLM response that should be a Python list of strings.

    Returns the list on success, or None if parsing fails.
    """
    cleaned = _clean_llm_list_response(raw)
    if not cleaned.startswith("["):
        match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        else:
            return None

    for parser in (ast.literal_eval, json.loads):
        try:
            result = parser(cleaned)
            if isinstance(result, list):
                return [str(item) for item in result]
        except Exception:
            continue
    return None


class Filter:
    class Valves(BaseModel):
        openai_api_url: str = Field(
            default="https://api.openai.com",
            description="openai compatible endpoint",
        )
        model: str = Field(
            default="gpt-4o",
            description="Model to use to determine memory. An intelligent model is highly recommended.",
        )
        api_key: str = Field(
            default="",
            description="API key for OpenAI compatible endpoint",
        )
        priority: int = Field(default=15, description="Priority level")
        related_memories_n: int = Field(
            default=5,
            description="Number of related memories to consider when updating memories",
        )
        related_memories_dist: float = Field(
            default=0.8,
            description="Distance of memories to consider for updates. Smaller number = more closely related.",
        )
        save_assistant_response: bool = Field(
            default=False,
            description="Automatically save assistant responses as memories",
        )
        simplified_output: bool = Field(
            default=True,
            description="Show simplified 'Memory updated' message instead of detailed memory content.",
        )
        excluded_models: str = Field(
            default="",
            description="Comma-separated list of model names to exclude from memory processing.",
        )
        model_specific_settings: str = Field(
            default='{"character_name": {"openai_api_url": "http://localhost:11434", "api_key": "ollama", "model": "qwen2.5:7b"}}',
            description='JSON object with per-model API settings.',
        )
        disable_for_image_generation: bool = Field(
            default=True,
            description="Disable memory injection for image generation requests.",
        )

    class UserValves(BaseModel):
        show_status: bool = Field(
            default=True, description="Show status of the action."
        )
        openai_api_url: Optional[str] = Field(
            default=None,
            description="User-specific openai compatible endpoint (overrides global)",
        )
        model: Optional[str] = Field(
            default=None,
            description="User-specific model to use (overrides global).",
        )
        api_key: Optional[str] = Field(
            default=None, description="User-specific API key (overrides global)"
        )
        messages_to_consider: int = Field(
            default=4,
            description="Number of messages to consider for memory processing.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        log.info("Auto Memory extension loaded (v4.0.0)")

    # ------------------------------------------------------------------
    # inlet: inject stored memories into the conversation context
    # ------------------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        log.info("inlet called")

        if self.valves.excluded_models and self._should_exclude_model(body, self.valves.excluded_models):
            log.info("Skipping memory injection for excluded model")
            return body

        if self.valves.disable_for_image_generation and self._is_image_generation_request(body):
            log.info("Skipping memory injection for image generation request")
            return body

        if not __user__:
            log.debug("No user context in inlet, skipping memory injection")
            return body

        user_id = __user__["id"]
        log.info("User detected: %s", user_id)

        try:
            user = await Users.get_user_by_id(user_id)
            if not user:
                log.warning("User lookup returned None for id=%s", user_id)
                return body

            memories = await self._get_all_memories(user)
            if memories:
                self._inject_memories_into_conversation(body, memories)
        except Exception:
            log.exception("Error retrieving/injecting memories in inlet")

        return body

    # ------------------------------------------------------------------
    # outlet: analyse the conversation and extract new memories
    # ------------------------------------------------------------------
    async def outlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        log.info("outlet called")

        if not __user__:
            log.warning("No user context in outlet, skipping")
            return body

        user_id = __user__["id"]
        self.user_valves = __user__.get("valves", self.UserValves())

        try:
            user = await Users.get_user_by_id(user_id)
        except Exception:
            log.exception("Failed to look up user id=%s", user_id)
            return body

        if not user:
            log.warning("User lookup returned None for id=%s", user_id)
            return body

        log.info("User detected: %s (%s)", user.name, user_id)

        if self.valves.excluded_models and self._should_exclude_model(body, self.valves.excluded_models):
            log.info("Skipping memory processing for excluded model")
            return body

        if self.valves.disable_for_image_generation and self._is_image_generation_request(body):
            log.info("Skipping memory processing for image generation request")
            return body

        # --- Analyse messages for new memories ---
        if len(body.get("messages", [])) >= 2:
            await self._process_conversation_memories(body, user, __user__, __event_emitter__)

        # --- Auto-save assistant response if enabled ---
        if self.valves.save_assistant_response and body.get("messages"):
            await self._save_assistant_response(body, user, __event_emitter__)

        return body

    # ------------------------------------------------------------------
    # Memory retrieval
    # ------------------------------------------------------------------
    async def _get_all_memories(self, user: UserModel) -> list[str]:
        """Retrieve all memories for a user, formatted with timestamps."""
        try:
            memories = await Memories.get_memories_by_user_id(user.id)
            if not memories:
                log.debug("No memories found for user %s", user.id)
                return []

            result = []
            for mem in memories:
                ts = _format_timestamp(getattr(mem, "created_at", time.time()))
                result.append(f"{mem.content} (on {ts})")

            log.info("Retrieved %d memories for user %s", len(result), user.id)
            return result
        except Exception:
            log.exception("Error getting memories for user %s", user.id)
            return []

    # ------------------------------------------------------------------
    # Memory injection
    # ------------------------------------------------------------------
    def _inject_memories_into_conversation(self, body: dict, memories: list[str]):
        """Prepend memory context to the first user message."""
        if not memories or not body.get("messages"):
            return

        memory_block = "\n".join(f"- {m}" for m in memories)
        memory_context = (
            "<MEMORY_CONTEXT>\n"
            "You have access to the user's personal memories below. These are facts about the user "
            "that may be relevant to your conversation.\n\n"
            "IMPORTANT INSTRUCTIONS:\n"
            "- Only reference memories when they are directly relevant to the current conversation\n"
            "- Do not list, enumerate, or mention memories unless specifically asked\n"
            "- Do not say things like \"I remember you mentioned...\" or \"Based on your memories...\"\n"
            "- Use the information naturally as context to provide better, more personalized responses\n"
            "- If memories are not relevant to the current topic, ignore them completely\n\n"
            f"USER MEMORIES:\n{memory_block}\n"
            "</MEMORY_CONTEXT>\n\n"
        )

        for message in body["messages"]:
            if message.get("role") == "user":
                original = message.get("content", "")
                if isinstance(original, str) and not original.startswith("<MEMORY_CONTEXT>"):
                    message["content"] = memory_context + original
                    log.info("Injected %d memories into conversation", len(memories))
                else:
                    log.debug("Memory context already present, skipping injection")
                break

    # ------------------------------------------------------------------
    # Conversation analysis
    # ------------------------------------------------------------------
    async def _process_conversation_memories(
        self,
        body: dict,
        user: UserModel,
        __user__: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
    ):
        """Extract memories from the latest conversation exchange."""
        stringified_messages = []
        for i in range(1, self.user_valves.messages_to_consider + 1):
            if i > len(body["messages"]):
                break
            try:
                message = body["messages"][-i]
                content = message.get("content", "")

                if message.get("role") == "assistant" and not self.valves.save_assistant_response:
                    continue

                if message.get("role") == "user" and isinstance(content, str) and "<MEMORY_CONTEXT>" in content:
                    if content.startswith("<MEMORY_CONTEXT>"):
                        content = content.split("</MEMORY_CONTEXT>\n\n", 1)[-1]
                    else:
                        content = re.sub(
                            r"<MEMORY_CONTEXT>.*?</MEMORY_CONTEXT>\n\n", "", content, flags=re.DOTALL
                        )

                stringified_messages.append(
                    STRINGIFIED_MESSAGE_TEMPLATE.format(
                        index=i, role=message.get("role", "unknown"), content=content
                    )
                )
            except Exception:
                log.exception("Error stringifying message at index -%d", i)

        if not stringified_messages:
            return

        prompt_string = "\n".join(stringified_messages)
        log.info("Messages analysed, prompt length: %d chars", len(prompt_string))

        # --- Identify candidate memories via LLM ---
        try:
            log.info("LLM request started (identify memories)")
            raw_response = await self._query_openai_api(
                system_prompt=IDENTIFY_MEMORIES_PROMPT,
                prompt=prompt_string,
                body=body,
            )
            log.info("LLM response received, length: %d", len(raw_response))
        except Exception:
            log.exception("LLM request failed during memory identification")
            await __event_emitter__(
                {
                    "type": "notification",
                    "data": {"type": "error", "content": "Memory identification failed (LLM error)"},
                }
            )
            return

        # --- Parse the response ---
        memory_list = _parse_list_response(raw_response)
        if memory_list is None:
            log.warning("Could not parse LLM response as list: %s", repr(raw_response[:200]))
            return

        if not memory_list:
            log.info("No new memories identified")
            return

        log.info("Candidate memories extracted: %d", len(memory_list))
        for mem in memory_list:
            log.debug("  candidate: %s", mem)

        # --- Store memories ---
        try:
            stored = await self._process_memories(memory_list, user, body, __user__)
            if stored and self.user_valves.show_status:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "Memory updated", "done": True}}
                )
                content = "Memory stored successfully"
                if not self.valves.simplified_output:
                    content = f"Stored {len(memory_list)} new memor{'ies' if len(memory_list) != 1 else 'y'}"
                await __event_emitter__(
                    {"type": "notification", "data": {"type": "success", "content": content}}
                )
        except Exception:
            log.exception("Memory processing failed")
            await __event_emitter__(
                {"type": "notification", "data": {"type": "error", "content": "Memory storage failed"}}
            )

    # ------------------------------------------------------------------
    # Assistant response auto-save
    # ------------------------------------------------------------------
    async def _save_assistant_response(
        self,
        body: dict,
        user: UserModel,
        __event_emitter__: Callable[[Any], Awaitable[None]],
    ):
        last_message = body["messages"][-1]
        if last_message.get("role") != "assistant":
            return

        content = last_message.get("content", "")
        if not content:
            return

        log.info("Saving assistant response as memory (first 100 chars): %s", content[:100])
        try:
            await self._store_single_memory(content, user)
            if self.user_valves.show_status:
                await __event_emitter__(
                    {"type": "notification", "data": {"type": "success", "content": "Assistant memory saved"}}
                )
        except Exception:
            log.exception("Error saving assistant memory")
            if self.user_valves.show_status:
                await __event_emitter__(
                    {"type": "notification", "data": {"type": "error", "content": "Error saving assistant memory"}}
                )

    # ------------------------------------------------------------------
    # Memory processing pipeline
    # ------------------------------------------------------------------
    async def _process_memories(
        self,
        memory_list: list[str],
        user: UserModel,
        body: dict,
        __user__: dict,
    ) -> bool:
        """De-duplicate, consolidate, and store a batch of candidate memories."""
        # Remove exact duplicates within the batch
        unique = []
        seen_lower: set[str] = set()
        for mem in memory_list:
            key = mem.lower().strip()
            if key not in seen_lower:
                seen_lower.add(key)
                unique.append(mem)

        if len(unique) < len(memory_list):
            log.info("Removed %d exact duplicates from batch", len(memory_list) - len(unique))

        # Batch-consolidate if multiple candidates
        if len(unique) > 1:
            consolidated = await self._consolidate_batch(unique, body, __user__)
            if consolidated is not None:
                unique = consolidated

        for mem in unique:
            await self._store_memory_with_dedup(mem, user, body, __user__)

        return True

    async def _consolidate_batch(
        self, memories: list[str], body: dict, __user__: dict
    ) -> list[str] | None:
        """Use the LLM to resolve contradictions within a single batch."""
        prompt = (
            f"You have {len(memories)} new memories from the same conversation "
            "that need to be consolidated:\n\n"
            f"{json.dumps([{'fact': m, 'created_at': time.time()} for m in memories])}\n\n"
            "If any of these memories contradict each other (like 'loves X' then 'hates X'), "
            "keep only the LAST one mentioned. If they're all compatible, keep them all.\n\n"
            "Return the final list as a Python list of strings."
        )
        try:
            raw = await self._query_openai_api(
                system_prompt="You are consolidating memories from a single conversation. Keep the most recent when there are contradictions.",
                prompt=prompt,
                body=body,
            )
            result = _parse_list_response(raw)
            if result is not None:
                log.info("Batch consolidation: %d -> %d memories", len(memories), len(result))
                return result
            log.warning("Batch consolidation produced unparseable response")
        except Exception:
            log.exception("Batch consolidation failed, proceeding with individual memories")
        return None

    async def _store_memory_with_dedup(
        self,
        memory: str,
        user: UserModel,
        body: dict,
        __user__: dict,
    ):
        """Find similar existing memories, consolidate if needed, then store."""
        # Find similar existing memories
        try:
            similar = await self._find_similar_memories(memory, user)
        except Exception:
            log.exception("Similarity search failed for '%s', storing without dedup", memory)
            await self._store_single_memory(memory, user)
            return

        if not similar:
            log.debug("No similar memories found for '%s'", memory)
            await self._store_single_memory(memory, user)
            return

        log.info("Found %d similar memories for '%s'", len(similar), memory)
        for s in similar:
            log.debug("  similar (dist=%.3f): %s", s["distance"], s["fact"])

        # Build fact list for consolidation
        fact_list = [
            {"fact": item["fact"], "created_at": item["metadata"].get("created_at", 0)}
            for item in similar
        ]
        fact_list.append({"fact": memory, "created_at": time.time()})

        # Consolidate via LLM
        try:
            log.info("LLM request started (consolidate memories)")
            raw = await self._query_openai_api(
                system_prompt=CONSOLIDATE_MEMORIES_PROMPT,
                prompt=json.dumps(fact_list),
                body=body,
            )
            log.info("LLM response received (consolidation)")
            consolidated = _parse_list_response(raw)
        except Exception:
            log.exception("Consolidation LLM call failed")
            consolidated = None

        if consolidated is None:
            # Fallback: skip near-exact duplicates, store otherwise
            for item in similar:
                if item["distance"] < 0.1:
                    log.info("Duplicate detected (dist=%.3f), skipping '%s'", item["distance"], memory)
                    return
            await self._store_single_memory(memory, user)
            return

        # Determine if consolidation actually changed anything
        original_facts = {item["fact"] for item in fact_list}
        consolidated_set = set(consolidated)

        if len(consolidated) < len(fact_list) or (original_facts != consolidated_set and similar):
            log.info("Consolidation resolved: %d -> %d memories", len(fact_list), len(consolidated))
            # Delete old related memories
            for item in similar:
                try:
                    await self._delete_single_memory(item["id"], user)
                    log.info("Deleted old memory: %s", item["id"])
                except Exception:
                    log.exception("Failed to delete memory %s", item["id"])
            # Store consolidated results
            for mem in consolidated:
                await self._store_single_memory(mem, user)
        else:
            log.info("No consolidation needed, storing new memory")
            await self._store_single_memory(memory, user)

    # ------------------------------------------------------------------
    # Low-level memory CRUD (model layer, not router layer)
    # ------------------------------------------------------------------
    async def _store_single_memory(self, content: str, user: UserModel):
        """Insert a memory into the DB and sync its embedding to the vector store."""
        try:
            memory_obj = await Memories.insert_new_memory(user.id, content)
            log.info("Memory written: '%s' (id=%s)", content[:80], memory_obj.id)
        except Exception:
            log.exception("DB insert failed for memory: '%s'", content[:80])
            raise

        # Best-effort vector embedding sync
        await self._upsert_memory_vector(memory_obj, user)

    async def _delete_single_memory(self, memory_id: str, user: UserModel):
        """Delete a memory from the DB and remove it from the vector store."""
        try:
            await Memories.delete_memory_by_id_and_user_id(memory_id, user.id)
            log.info("Memory deleted from DB: %s", memory_id)
        except Exception:
            log.exception("DB delete failed for memory %s", memory_id)
            raise

        # Best-effort vector removal
        if ASYNC_VECTOR_DB_CLIENT is not None:
            try:
                await ASYNC_VECTOR_DB_CLIENT.delete(
                    collection_name=f"user-memory-{user.id}", ids=[memory_id]
                )
                log.debug("Memory deleted from vector store: %s", memory_id)
            except Exception:
                log.warning("Vector delete failed for memory %s (non-fatal)", memory_id)

    async def _upsert_memory_vector(self, memory: MemoryModel, user: UserModel):
        """Embed a memory and upsert it into the vector store.

        This keeps the vector DB in sync with the SQL database so that
        Open WebUI's built-in memory recall and the plugin's similarity
        search both work correctly.

        Uses the app's own EMBEDDING_FUNCTION when available.  Falls back
        silently if embeddings or the vector client are unavailable.
        """
        if ASYNC_VECTOR_DB_CLIENT is None:
            return

        # We need the app's embedding function.  It is attached to the
        # ASGI app state at startup.  We obtain it via the webui_app
        # singleton which is always importable even if we don't use it
        # for fake Request objects any more.
        try:
            from open_webui.main import app as _app
            embed_fn = getattr(_app.state, "EMBEDDING_FUNCTION", None)
            if embed_fn is None:
                log.debug("EMBEDDING_FUNCTION not available, skipping vector upsert")
                return

            vector = await embed_fn(memory.content, user=user)
            await ASYNC_VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user.id}",
                items=[
                    {
                        "id": memory.id,
                        "text": memory.content,
                        "vector": vector,
                        "metadata": {
                            "created_at": memory.created_at,
                        },
                    }
                ],
            )
            log.debug("Vector upserted for memory %s", memory.id)
        except Exception:
            log.warning("Vector upsert failed for memory %s (non-fatal)", memory.id, exc_info=True)

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------
    async def _find_similar_memories(self, memory: str, user: UserModel) -> list[dict]:
        """Find memories similar to `memory` for the given user.

        Tries vector search first; falls back to text-based Jaccard
        similarity if embeddings or the vector DB are unavailable.
        """
        # Attempt vector-based search first
        vector_results = await self._find_similar_vector(memory, user)
        if vector_results is not None:
            return vector_results

        # Fallback: text-based similarity
        return await self._find_similar_text(memory, user)

    async def _find_similar_vector(self, memory: str, user: UserModel) -> list[dict] | None:
        """Search the vector store for similar memories. Returns None if unavailable."""
        if ASYNC_VECTOR_DB_CLIENT is None:
            return None

        try:
            from open_webui.main import app as _app
            embed_fn = getattr(_app.state, "EMBEDDING_FUNCTION", None)
            if embed_fn is None:
                return None

            vector = await embed_fn(memory, user=user)
            results = await ASYNC_VECTOR_DB_CLIENT.search(
                collection_name=f"user-memory-{user.id}",
                vectors=[vector],
                limit=self.valves.related_memories_n,
            )

            if not results or not results.ids or not results.ids[0]:
                return []

            structured = []
            ids = results.ids[0]
            documents = results.documents[0] if results.documents else []
            metadatas = results.metadatas[0] if results.metadatas else []
            distances = results.distances[0] if results.distances else []

            for i in range(len(ids)):
                dist = distances[i] if i < len(distances) else 1.0
                if dist < self.valves.related_memories_dist:
                    structured.append(
                        {
                            "id": ids[i],
                            "fact": documents[i] if i < len(documents) else "",
                            "metadata": metadatas[i] if i < len(metadatas) else {},
                            "distance": dist,
                        }
                    )

            log.info("Vector similarity search returned %d results for '%s'", len(structured), memory[:50])
            return structured

        except Exception:
            log.warning("Vector similarity search failed, will fall back to text", exc_info=True)
            return None

    async def _find_similar_text(self, memory: str, user: UserModel) -> list[dict]:
        """Fallback text-based similarity using Jaccard distance."""
        log.info("Using text-based similarity search for '%s'", memory[:50])
        try:
            all_memories = await Memories.get_memories_by_user_id(user.id)
            if not all_memories:
                return []

            log.debug("Comparing against %d existing memories", len(all_memories))
            results = []
            memory_lower = memory.lower().strip()

            for existing in all_memories:
                existing_content = (existing.content or "").lower().strip()
                similarity = self._calculate_text_similarity(memory_lower, existing_content)
                distance = 1.0 - similarity

                if distance < self.valves.related_memories_dist:
                    results.append(
                        {
                            "id": existing.id,
                            "fact": existing.content,
                            "metadata": {"created_at": getattr(existing, "created_at", time.time())},
                            "distance": distance,
                        }
                    )

            results.sort(key=lambda x: x["distance"])
            final = results[: self.valves.related_memories_n]
            log.info("Text similarity search returned %d results", len(final))
            return final

        except Exception:
            log.exception("Text-based similarity search failed")
            return []

    @staticmethod
    def _calculate_text_similarity(text1: str, text2: str) -> float:
        """Jaccard similarity on word sets."""
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0
        if text1 in text2 or text2 in text1:
            return 0.8

        words1 = set(text1.split())
        words2 = set(text2.split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    # ------------------------------------------------------------------
    # LLM communication
    # ------------------------------------------------------------------
    async def _query_openai_api(self, system_prompt: str, prompt: str, body: dict | None = None) -> str:
        """Call an OpenAI-compatible chat completions endpoint."""
        if body:
            api_url, model, api_key = self._get_effective_settings(body)
        else:
            api_url = self.user_valves.openai_api_url or self.valves.openai_api_url
            model = self.user_valves.model or self.valves.model
            api_key = self.user_valves.api_key or self.valves.api_key

        url = f"{api_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }

        log.debug("LLM request: POST %s (model=%s)", url, model)

        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(url, headers=headers, json=payload)
                response.raise_for_status()

                response_text = await response.text()
                if not response_text or not response_text.strip():
                    raise ValueError("Empty response from LLM API")

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    cleaned = response_text.strip().lstrip("\ufeff")
                    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
                    data = json.loads(cleaned)

                if "choices" not in data or not data["choices"]:
                    raise ValueError("LLM response missing 'choices'")

                content = data["choices"][0].get("message", {}).get("content")
                if content is None:
                    raise ValueError("LLM response missing message content")

                log.debug("LLM response received (%d chars)", len(content))
                return content

        except aiohttp.ClientError as exc:
            log.error("LLM HTTP error: %s", exc)
            raise
        except Exception as exc:
            log.error("LLM API error: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Settings resolution
    # ------------------------------------------------------------------
    def _get_effective_settings(self, body: dict) -> tuple[str, str, str]:
        """Resolve API URL, model, and key for the current request."""
        model_name = self._get_current_model_name(body)
        model_settings = self._get_model_specific_settings(model_name)

        api_url = self.user_valves.openai_api_url or self.valves.openai_api_url
        model = self.user_valves.model or self.valves.model
        api_key = self.user_valves.api_key or self.valves.api_key

        if model_settings:
            api_url = model_settings.get("openai_api_url", api_url)
            model = model_settings.get("model", model)
            api_key = model_settings.get("api_key", api_key)
            log.debug("Using model-specific settings for '%s': model=%s", model_name, model)

        return api_url, model, api_key

    def _get_current_model_name(self, body: dict) -> str:
        model_name = ""
        model_title = ""

        if isinstance(body.get("chat"), dict):
            for info in body["chat"].get("models", []):
                if isinstance(info, dict):
                    model_name = info.get("name", model_name)
                    model_title = info.get("title", model_title)

        if isinstance(body.get("model_info"), dict):
            model_name = body["model_info"].get("name", model_name)
            model_title = body["model_info"].get("title", model_title)

        return model_name or model_title or body.get("model", "")

    def _get_model_specific_settings(self, model_name: str) -> dict:
        if not self.valves.model_specific_settings or not model_name:
            return {}
        try:
            return json.loads(self.valves.model_specific_settings).get(model_name, {})
        except (json.JSONDecodeError, TypeError):
            log.warning("Failed to parse model_specific_settings JSON")
            return {}

    # ------------------------------------------------------------------
    # Request filtering helpers
    # ------------------------------------------------------------------
    def _is_image_generation_request(self, body: dict) -> bool:
        if not body:
            return False

        image_params = {"size", "n", "response_format"}
        has_image_params = bool(image_params & body.keys())

        has_prompt_only = "prompt" in body and len([k for k in body if k not in ("prompt", "model")]) <= 2

        metadata = body.get("metadata", {}) or {}
        features = body.get("features", {}) or {}
        options = body.get("options", {}) or {}

        checks = [
            has_image_params,
            has_prompt_only and "prompt" in body,
            metadata.get("image_generation") or metadata.get("generate_image"),
            features.get("image_generation") or options.get("generate_image"),
            body.get("image_generation", False) or body.get("generate_image", False),
            any(m in body.get("model", "").lower() for m in ("dall-e", "stable-diffusion", "imagen", "midjourney")),
            body.get("backend") in ("comfyui", "automatic1111", "stable-diffusion"),
        ]

        is_image = any(checks)
        if is_image:
            log.info("Detected image generation request")
        return is_image

    def _should_exclude_model(self, body: dict, excluded_models: str) -> bool:
        if not excluded_models:
            return False

        excluded_list = [m.strip().strip("\"'") for m in excluded_models.split(",")]
        candidates = [
            body.get("model", ""),
            body.get("model_id", ""),
            self._get_current_model_name(body),
        ]

        for candidate in candidates:
            if candidate and candidate in excluded_list:
                log.info("Model '%s' is in exclusion list", candidate)
                return True

        return False
