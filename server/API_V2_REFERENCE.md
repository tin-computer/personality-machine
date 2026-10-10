# Personality Machine API v2 Reference

Base URL: `https://api.emotionmachine.ai/v2` (hosted) or `http://localhost:8100/v2` (self-hosted)

---

## 1. The Model

### What is Emotion Machine?

Emotion Machine is an API for building AI companions with persistent relationships. Unlike stateless chat APIs where each request is independent, Emotion Machine maintains a continuous relationship between your users and AI companions—remembering context, tracking state, and enabling proactive engagement.

The API is built around three core principles:

1. **Relationships, not sessions** — A user's relationship with a companion persists forever. State, memory, and conversation history survive across sessions, devices, and time.

2. **Developer control, AI enhancement** — You own the data model. Profile schemas, behaviors, and state are defined by you. The AI can read state and trigger behaviors, but only your code decides what persists.

3. **Progressive complexity** — Start with a single line of code. Add behaviors, voice, and proactive messaging as your product requires them.

---

### Core Concepts

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              COMPANION                                  │
│  (The AI entity - configured once by developer)                         │
│                                                                         │
│   name: "Aria"                                                          │
│   system_prompt: "You are a supportive coach..."                        │
│   voice: "sage"                                                         │
│   behaviors: [mood_check, daily_summary, ...]                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│   RELATIONSHIP       │ │   RELATIONSHIP       │ │   RELATIONSHIP       │
│   (Aria + Alice)     │ │   (Aria + Bob)       │ │   (Aria + Carol)     │
│                      │ │                      │ │                      │
│   profile: {...}     │ │   profile: {...}     │ │   profile: {...}     │
│   memory: [...]      │ │   memory: [...]      │ │   memory: [...]      │
│   messages: [...]    │ │   messages: [...]    │ │   messages: [...]    │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

| Concept | Description | Lifespan |
|---------|-------------|----------|
| **Companion** | An AI entity with personality, voice, and behaviors | Permanent (until deleted) |
| **Relationship** | A user-companion pair with persistent state | Permanent (per user-companion) |
| **Session** | An explicit, bounded interaction (optional) | Minutes to hours |
| **Turn** | A single user message + assistant response | Seconds |

**Companion** — The AI entity you configure: system prompt, voice settings, behaviors, knowledge base, and tools. A single companion can have relationships with millions of users.

**Relationship** — Created when a user first interacts with a companion. Stores that user's profile, conversation history, and memory. The relationship is the unit of state—everything about a specific user-companion pair lives here.

**Session** — Optional. Use sessions when you need explicit boundaries: therapy sessions, coaching calls, or billing periods. Most apps use continuous chat (no explicit sessions).

**Turn** — One user message plus one assistant response. Turns are serialized per relationship—only one turn runs at a time to prevent race conditions.

---

### State Hierarchy

Each relationship maintains three types of state:

```
┌─────────────────────────────────────────────────────────────────────┐
│                           PROFILE                                   │
│  Developer-owned structured data. You define the schema.            │
│  Persists forever. Read by AI, written by behaviors.                │
│                                                                     │
│  {                                                                  │
│    "user": {"name": "Sarah", "age": 32, "goals": [...]},           │
│    "app": {"subscription": "premium", "timezone": "PST"}            │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                           MEMORY                                     │
│  Long-term memory that persists forever across sessions.             │
│  Two versions available (configurable via memory.version):           │
│                                                                     │
│  Version 1 (Vector-Based) — Semantic search with embeddings          │
│  • Memories scored for importance and retrieved via similarity       │
│  • Best for: large memory stores, selective retrieval                │
│                                                                     │
│  Version 2 (Scratchpad) — ChatGPT-style flat list                    │
│  • Entire scratchpad injected into prompt                            │
│  • AI can ADD/UPDATE/DELETE entries during conversation              │
│  • Best for: simpler use cases, full context visibility              │
│                                                                     │
│  # MEMORY                                                            │
│  - User's name is Sarah (identity)                                   │
│  - Got promoted to Senior PM last month (event)                      │
│  - Prefers direct feedback (preference)                              │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        SESSION STATE                                │
│  Temporary scratch space. Only exists during a session.             │
│  Cleared when session ends.                                         │
│                                                                     │
│  {                                                                  │
│    "current_goal": "work through presentation anxiety",             │
│    "steps_completed": ["breathing", "reframing"]                    │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

| Bucket | Purpose | Who Writes | Lifespan |
|--------|---------|------------|----------|
| **Profile** | Structured user/companion data | Behaviors, API | Forever |
| **Memory** | Long-term semantic memories | System (auto-extracted), API | Forever |
| **Session State** | Temporary session data | Behaviors | Until session ends |

#### Memory Systems

Emotion Machine supports two memory systems. Choose based on your use case:

| Aspect | Version 1 (Vector) | Version 2 (Scratchpad) |
|--------|-------------------|------------------------|
| **Storage** | Vector embeddings with importance scores | Flat list of entries |
| **Retrieval** | Similarity search, top-k results | Entire scratchpad injected |
| **Best for** | Large memory stores, selective recall | Full context visibility, ChatGPT-style |
| **AI writes** | Automatic extraction after turns | ADD/UPDATE/DELETE during conversation |
| **Config** | `memory.version: 1` (default) | `memory.version: 2` |

---

#### Memory Version 1: Vector-Based

The original memory system uses vector embeddings for semantic retrieval:

| Component | Description |
|-----------|-------------|
| **Importance Scoring** | LLM rates memories 1-10 with heuristic floors for identity facts, preferences, and goals |
| **Retrieval Gating** | Keyword triggers (`"remember"`, `"my name is"`, etc.) or LLM classifier decides when to search |
| **Vector Search** | Embeddings via `text-embedding-3-small`, ranked by similarity + recency decay |
| **Saliency Threshold** | Only memories above similarity threshold (default 0.2-0.35) are retrieved |
| **Context Injection** | Top memories formatted and added to system prompt |

**V1 Configuration options**:
- `top_k` — Maximum memories to retrieve (default: 15)
- `min_saliency` — Minimum similarity score (default: 0.2)
- `recency` — Lambda decay factor for recency weighting (default: 0.995)
- `memory_evaluation_prompt` — Custom guidance for importance scoring

```python
# Example: Memory V1 configuration
companion = await em.companions.create(
    name="Assistant",
    config={
        "memory": {
            "enabled": True,
            "version": 1,  # Vector-based (default)
            "top_k": 15,
            "min_saliency": 0.2
        }
    }
)
```

---

#### Memory Version 2: Scratchpad

A ChatGPT-style memory scratchpad where the AI maintains a dynamic list of facts about the user:

```json
[
  {
    "id": "mem_abc123",
    "content": "User's name is Sarah",
    "type": "identity",
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:00:00Z"
  },
  {
    "id": "mem_def456",
    "content": "Got promoted to Senior PM last month",
    "type": "event",
    "created_at": "2024-01-10T08:00:00Z",
    "updated_at": "2024-01-10T08:00:00Z"
  }
]
```

| Feature | Description |
|---------|-------------|
| **Format** | Flat list of semantic entries, sorted by last updated |
| **Entry Types** | `identity`, `preference`, `goal`, `event`, `relationship`, `other` |
| **AI Control** | AI analyzes each turn and can ADD, UPDATE, DELETE entries |
| **Injection** | Entire scratchpad formatted and injected into system prompt |
| **Soft Limit** | Configurable max entries (default: 100) with warnings when exceeded |

**V2 Configuration options**:
- `max_entries` — Maximum scratchpad entries (default: 100)
- `model` — LLM for memory analysis (default: `google/gemini-2.0-flash-001`)
- `ingestion_prompt` — Custom prompt for memory extraction logic

```python
# Example: Memory V2 configuration
companion = await em.companions.create(
    name="Coach",
    config={
        "memory": {
            "enabled": True,
            "version": 2,  # Scratchpad
            "max_entries": 100
        }
    }
)
```

**V2 API Endpoints**:

```http
# List all memory entries
GET /v2/relationships/{relationship_id}/memory

# Add a memory entry manually
POST /v2/relationships/{relationship_id}/memory
{"content": "User prefers morning meetings", "type": "preference"}

# Update a memory entry
PATCH /v2/relationships/{relationship_id}/memory/{entry_id}
{"content": "User now prefers afternoon meetings"}

# Delete a memory entry
DELETE /v2/relationships/{relationship_id}/memory/{entry_id}

# Clear all memories
DELETE /v2/relationships/{relationship_id}/memory
```

---

### Communication Methods

The API provides four ways to communicate, each optimized for different use cases:

| Method | Transport | Use Case | Proactive Messages? |
|--------|-----------|----------|---------------------|
| `rel.send()` | REST | Simple request/response | No |
| `rel.stream()` | SSE | Streaming UI | No |
| `rel.connect()` | WebSocket | Real-time apps, chat | Yes |
| `rel.voice()` | WebSocket | Voice conversations | Yes |

**REST (`send`)** — Single HTTP request, single response. Best for server-to-server, simple integrations, and when you don't need streaming.

**SSE (`stream`)** — Server-Sent Events for streaming responses token-by-token. Best for chat UIs where you want to show the response as it generates.

**WebSocket (`connect`)** — Full duplex connection for real-time apps. Supports proactive messages—the companion can message the user even when they haven't sent anything (via behaviors).

**Voice (`voice`)** — Real-time voice conversations over WebSocket. Audio streams bidirectionally. Shares state with text (same profile, memory, history).

---

### Behaviors

Behaviors are developer-defined logic that runs during conversations. They bridge the gap between AI capabilities and your application logic.

```
User sends message
    │
    ├─► Priority behaviors execute (sync)
    │   └─► Can inject context into system prompt
    │
    ├─► LLM generates response
    │
    └─► Async behaviors execute (background)
        └─► Can update profile, send proactive messages
```

| Type | Execution | Use Cases |
|------|-----------|-----------|
| **Priority (sync)** | Before LLM response | Inject context, modify prompt, real-time analysis |
| **Async** | After turn completes | Update profile, webhooks, proactive messages |

**Triggers:**
- `always` — Every turn
- `every:N` — Every Nth turn
- `keyword:X,Y` — When message contains keywords
- `cron:EXPR` — Scheduled (e.g., daily check-in)
- `idle:N` — After N minutes of inactivity
- API — Programmatically triggered

Behaviors have access to a `ctx` object with the full relationship context: profile, messages, session state, and utilities like `ctx.llm.run()` for calling LLMs within behavior code.

---

### Turn Ordering

**WebSocket connections** serialize turns per-connection:

| Scenario | Behavior |
|----------|----------|
| Message arrives while idle | Processed immediately |
| Message arrives mid-turn | Cancels current turn, starts new one |
| Cancel current turn | Send `{"type": "cancel"}` |

```json
// Cancel the current turn
{"type": "cancel"}

// Server responds with
{"type": "cancelled", "turn_id": "..."}
```

**REST/SSE requests** process independently—there is no cross-channel coordination. If you need strict turn serialization across multiple clients, implement locking in your application layer.

---

## 2. Quick Start

### Installation

```bash
pip install emotion-machine
```

Requires Python 3.10+. Dependencies: `httpx`, `websockets`.

---

### Authentication

All API calls require an API key. Get one from the Emotion Machine dashboard.

```python
from emotion_machine import EmotionMachine

# Via constructor
em = EmotionMachine(api_key="emk_live_a1b2c3d4e5f6....")

# Or via environment variable
# export EM_API_KEY=emk_live_a1b2c3d4e5f6....
em = EmotionMachine()
```

For REST calls without the SDK:

```bash
curl -X POST "https://api.emotionmachine.ai/v2/companions/{cid}/relationships/{uid}/messages" \
  -H "Authorization: Bearer emk_live_a1b2c3d4e5f6...." \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello!"}'
```

---

### Hello World (5 seconds)

```python
from emotion_machine import EmotionMachine

async with EmotionMachine(api_key="emk_live_a1b2c3d4e5f6....") as em:
    rel = em.relationship("companion_id", "user_123")
    response = await rel.send("Hello!")
    print(response["message"]["content"])
```

That's it. The relationship is created automatically on first message. No setup required.

---

### Progressive Examples

The SDK provides four levels of interaction, from simple to real-time:

#### Level 1: Simple Send (REST)

Single request, single response. Best for server-to-server or simple integrations.

```python
async with EmotionMachine(api_key="...") as em:
    rel = em.relationship(companion_id, user_id)

    # Send a message
    response = await rel.send("What's the weather like?")
    print(response["message"]["content"])

    # With config overrides
    response = await rel.send(
        "Tell me a joke",
        config={"inference": {"temperature": 0.9}}
    )
```

#### Level 2: Streaming (SSE)

Stream tokens as they're generated. Best for chat UIs.

```python
async with EmotionMachine(api_key="...") as em:
    rel = em.relationship(companion_id, user_id)

    async for chunk in rel.stream("Tell me a long story"):
        data = chunk.get("data", {})
        if isinstance(data, dict) and data.get("type") == "delta":
            print(data.get("data", {}).get("content", ""), end="", flush=True)
```

#### Level 3: WebSocket (Real-time)

Full duplex for real-time apps. Supports proactive messages from the companion.

```python
async with EmotionMachine(api_key="...") as em:
    rel = em.relationship(companion_id, user_id)

    async with rel.connect() as ws:
        await ws.send("Hello!")

        async for event in ws:
            match event["type"]:
                case "delta":
                    print(event["data"]["content"], end="")
                case "message":
                    print()  # Newline after complete message
                case "proactive":
                    # Companion initiated this message (via behavior)
                    print(f"\n[Companion]: {event['data']['content']}")
```

#### Level 4: Voice

Real-time voice conversations. Audio streams bidirectionally.

```python
async with EmotionMachine(api_key="...") as em:
    rel = em.relationship(companion_id, user_id)

    async with rel.voice(config={"voice_name": "sage"}) as voice:
        async for event in voice:
            if event["type"] == "audio":
                play_audio(event["data"])
            elif event["type"] == "transcript":
                print(f"Said: {event['data']['text']}")
```

---

### Create a Companion

Before you can chat, you need a companion. Create one via the dashboard or API:

```python
async with EmotionMachine(api_key="...") as em:
    companion = await em.companions.create(
        name="Coach",
        config={
            "system_prompt": {
                "full_system_prompt": "You are a supportive life coach."
            },
            "memory": {"enabled": True},
            "knowledge": {"enabled": True},
        }
    )
    print(f"Created companion: {companion['id']}")
```

---

### Manage User Profiles

Store structured data about the user:

```python
rel = em.relationship(companion_id, user_id)

# Set profile (replaces entirely)
await rel.profile_set({
    "user": {"name": "Sarah", "age": 28},
    "preferences": {"tone": "friendly", "topics": ["career", "wellness"]}
})

# Patch profile (merges changes)
await rel.profile_patch({"user": {"mood": "motivated"}})

# Get profile
profile = await rel.profile_get()
print(profile["user"]["name"])  # "Sarah"

# Clear profile
await rel.profile_clear()
```

---

### Using Sessions

For bounded interactions (therapy, coaching, billing):

```python
rel = em.relationship(companion_id, user_id)

# Start a session
session = await rel.session_start(type="coaching")

# Chat within the session
await session.send("Let's work on my goals today")
await session.send("I want to focus on productivity")

# End session and get summary
result = await session.end()
print(result["summary"])  # AI-generated summary
```

**Isolated sessions** don't affect the main relationship state:

```python
# Nothing from this session persists to the relationship
session = await rel.session_start(type="therapy", isolated=True)
```

---

### Check for Proactive Messages (REST)

If you're not using WebSocket, poll the inbox for proactive messages:

```python
rel = em.relationship(companion_id, user_id)

# Check for pending messages
messages = await rel.inbox_check()
for msg in messages:
    print(f"[{msg['created_at']}] {msg['content']}")

# Acknowledge messages
await rel.inbox_ack([m["id"] for m in messages])
```

---

### Error Handling

```python
from emotion_machine import APIError, WebSocketError

try:
    response = await rel.send("Hello!")
except APIError as e:
    print(f"API error {e.status_code}: {e.message}")
    # e.status_code: 400, 401, 404, 409, 429, 500
    # e.message: Human-readable error

try:
    async with rel.connect() as ws:
        async for event in ws:
            pass
except WebSocketError as e:
    print(f"WebSocket error: {e.message}")
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request (invalid parameters) |
| 401 | Unauthorized (invalid API key) |
| 404 | Not found (companion/relationship doesn't exist) |
| 409 | Conflict (turn in progress, or idempotency key reused) |
| 429 | Rate limited |
| 500 | Server error |

---

## 3. Developer Guide

This section provides comprehensive coverage of all Emotion Machine features.

---

### 3.1 Behaviors

Behaviors are developer-defined Python functions that run during conversations. They're the primary mechanism for:
- Injecting dynamic context into the AI's system prompt
- Updating user profiles based on conversation content
- Sending proactive messages to users
- Integrating with external systems via webhooks

#### Priority vs Async Behaviors

| Type | Execution | Blocks LLM? | Use Cases |
|------|-----------|-------------|-----------|
| **Priority** | Before LLM generates response | Yes | Inject context, analyze message, modify prompt |
| **Async** | After turn completes | No | Update state, webhooks, proactive messages |

```python
from emotion_machine import behavior

# Priority behavior - runs BEFORE the LLM response
@behavior(triggers=["always"], priority=True)
async def mood_analyzer(ctx):
    """Inject mood-aware guidance into the system prompt."""
    message = ctx.message.lower()

    if any(word in message for word in ["anxious", "worried", "stressed"]):
        ctx.profile.set("user.current_mood", "anxious")
        return "User seems anxious. Be warm, supportive, and validate their feelings."

    if any(word in message for word in ["happy", "excited", "great"]):
        ctx.profile.set("user.current_mood", "positive")
        return "User is in a positive mood. Match their energy."

    return None  # No prompt injection

# Async behavior - runs AFTER the response is sent
@behavior(triggers=["always"], priority=False)
async def track_engagement(ctx):
    """Track conversation metrics in the background."""
    turn_count = ctx.profile.get("stats.turn_count", 0) + 1
    ctx.profile.set("stats.turn_count", turn_count)
    ctx.profile.set("stats.last_active", ctx.timestamp)

    # Notify external system
    ctx.notify_webhook("engagement_update", {
        "user_id": ctx.user_id,
        "turn_count": turn_count
    })
```

#### Trigger Types

| Trigger | Syntax | Description |
|---------|--------|-------------|
| **always** | `["always"]` | Every message |
| **every:N** | `["every:5"]` | Every Nth message |
| **turn:N,M** | `["turn:1,5,10"]` | Specific turn numbers |
| **keyword:X,Y** | `["keyword:help,urgent"]` | When message contains any keyword |
| **cron:EXPR** | `["cron:0 9 * * *"]` | Cron schedule (UTC) |
| **idle:N** | `["idle:30"]` | After N minutes of user inactivity |
| **api** | `["api"]` | Only when triggered programmatically |

```python
# Runs on turn 1 (first message) only
@behavior(triggers=["turn:1"], priority=True)
async def welcome_message(ctx):
    return "This is the user's first message. Give a warm welcome."

# Runs every 5th message
@behavior(triggers=["every:5"], priority=True)
async def periodic_summary(ctx):
    return "Briefly summarize what you've discussed so far."

# Runs when user mentions help-related keywords
@behavior(triggers=["keyword:help,stuck,confused"], priority=True)
async def help_detector(ctx):
    return "User may need extra assistance. Be proactive in offering help."

# Runs daily at 9 AM UTC
@behavior(triggers=["cron:0 9 * * *"])
async def daily_checkin(ctx):
    ctx.send_message("Good morning! How are you feeling today?")

# Runs after 30 minutes of inactivity
@behavior(triggers=["idle:30"])
async def idle_nudge(ctx):
    ctx.send_message("Hey! Just checking in. Let me know if you need anything.")
```

#### The Context Object (`ctx`)

Behaviors receive a `ctx` object with full access to the relationship context:

```python
@behavior(triggers=["always"], priority=True)
async def example_behavior(ctx):
    # === Identity ===
    ctx.companion_id        # UUID of the companion
    ctx.relationship_id     # UUID of the relationship
    ctx.user_id             # External user ID (string)
    ctx.session_id          # Session UUID (None if no session)

    # === Trigger Info ===
    ctx.trigger_source      # What triggered: "always", "keyword", "cron", "idle", "api"
    ctx.trigger_details     # Details: "keyword:help", "cron:0 9 * * *", etc.
    ctx.turn_count          # Current turn number
    ctx.timestamp           # ISO timestamp of the message

    # === Message Content ===
    ctx.message             # Current user message (empty for cron/idle triggers)
    ctx.messages            # List of recent messages [{role, content, created_at}, ...]
    ctx.last_user_message   # Helper: last user message content
    ctx.conversation_text() # Formatted: "USER: ...\nASSISTANT: ..."

    # === Profile (persistent) ===
    ctx.profile.get("user.name")                    # Get value (dot notation)
    ctx.profile.get("user.age", default=0)          # With default
    ctx.profile.set("user.mood", "happy")           # Set value
    ctx.profile.delete("user.temp_data")            # Delete key

    # === Session State (temporary, if in session) ===
    ctx.session.get("current_step")
    ctx.session.set("current_step", 3)
    ctx.session.delete("draft")

    # === Effects ===
    ctx.send_message("Hello!", expires_in_hours=24) # Proactive message
    ctx.notify_webhook("event_name", {"data": ...}) # Webhook notification
    ctx.schedule_behavior("key", run_at="in 2 hours")

    # === LLM Access ===
    response = await ctx.llm.run(
        prompt="Analyze this: " + ctx.message,
        system="You are an analyst.",              # Optional
        model="google/gemini-2.0-flash-001",       # Optional (default)
        temperature=0.7,                            # Optional
        max_tokens=1000,                            # Optional
    )

    # Return value (priority behaviors only)
    return "This text is injected into the system prompt."
```

#### LLM Access in Behaviors

All behaviors (including isolated ones) can call LLMs via `ctx.llm.run()`:

```python
@behavior(triggers=["api"])
async def analyze_sentiment(ctx):
    """Use LLM to analyze sentiment and store in profile."""

    # Get recent conversation
    conversation = ctx.conversation_text()

    # Call LLM
    analysis = await ctx.llm.run(
        prompt=f"Analyze the sentiment of this conversation:\n\n{conversation}",
        system="Respond with JSON: {\"sentiment\": \"positive|negative|neutral\", \"confidence\": 0.0-1.0}",
        temperature=0.3,
    )

    # Parse and store
    import json
    result = json.loads(analysis)
    ctx.profile.set("analysis.sentiment", result["sentiment"])
    ctx.profile.set("analysis.confidence", result["confidence"])

    return None  # No prompt injection needed
```

**Note:** `ctx.llm.run()` routes through a dedicated Modal function with network access. This allows even isolated behaviors (which have `block_network=True`) to use LLMs.

#### Webhooks

Configure webhooks per-behavior to receive notifications when behaviors complete:

```python
# Via SDK when creating behavior
await em.behaviors.create(
    companion_id,
    behavior_key="mood_tracker",
    source_code="...",
    triggers=["always"],
    webhook_url="https://yourapp.com/hooks/behavior",
    webhook_secret="whsec_...",  # For signature verification
)

# Or notify from within behavior code
@behavior(triggers=["always"])
async def notify_backend(ctx):
    ctx.notify_webhook("mood_change", {
        "user_id": ctx.user_id,
        "mood": ctx.profile.get("user.mood"),
        "timestamp": ctx.timestamp,
    })
```

Webhook payload:

```json
{
  "event": "behavior.completed",
  "behavior_key": "mood_tracker",
  "status": "success",
  "relationship": {
    "id": "rel_123",
    "companion_id": "comp_456",
    "user_id": "alice"
  },
  "profile": { ... },
  "result": {
    "prompt_block": "User seems anxious...",
    "effects_applied": ["profile.user.mood"]
  },
  "timestamp": "2024-01-15T10:30:00Z",
  "signature": "sha256=..."
}
```

#### Testing Behaviors

Test behaviors locally before deploying:

```python
result = await em.behaviors.test(
    companion_id,
    "mood_tracker",
    message="I'm feeling really anxious today",
    profile={"user": {"name": "Sarah"}},  # Mock profile
)

print(result["prompt_block"])   # "User seems anxious..."
print(result["effects"])        # [{"set_profile": {"user.mood": "anxious"}}]
print(result["duration_ms"])    # 127
```

#### Deploying Behaviors

```python
# Deploy all decorated behaviors in current module
await em.behaviors.deploy(companion_id)

# Or create programmatically
await em.behaviors.create(
    companion_id,
    behavior_key="my_behavior",
    source_code='''
async def execute(ctx):
    if "help" in ctx.message.lower():
        return "User needs help. Be extra supportive."
    return None
''',
    triggers=["always"],
    priority=True,
)

# List behaviors
behaviors = await em.behaviors.list(companion_id)

# Delete behavior
await em.behaviors.delete(companion_id, "my_behavior")
```

#### Triggering Behaviors via API

```python
# Trigger a behavior programmatically
result = await rel.behavior_trigger(
    "analyze_sentiment",
    context={"custom_data": "value"}  # Optional context
)
```

---

### 3.2 Profile Management

Profile is developer-owned structured data stored per relationship. Use it for user preferences, app state, and any data you want to persist.

#### Profile Schema (Optional)

Define a schema at the companion level to set default values and structure for all user profiles. When a relationship's profile is retrieved, it's automatically merged with the schema—new fields appear with their defaults.

```python
# Define profile schema when creating companion
companion = await em.companions.create(
    name="Coach",
    config={
        "profile_schema": {
            "user": {
                "name": "",
                "timezone": "UTC",
                "preferences": {
                    "notifications": True,
                    "daily_checkin": False
                }
            },
            "stats": {
                "sessions_completed": 0,
                "streak_days": 0
            }
        }
    }
)
```

**Merge-on-read behavior:**
- Schema provides default structure and values
- Existing profile data takes precedence over schema defaults
- New schema fields automatically appear in profile responses
- Schema updates don't overwrite existing user data

```python
# Schema defines: {"user": {"name": "", "timezone": "UTC"}}
# User's actual profile: {"user": {"name": "Sarah"}}
# GET profile returns: {"user": {"name": "Sarah", "timezone": "UTC"}}
```

Update the schema via the dashboard Profile tab or API:

```http
PATCH /v1/companions/{companion_id}
Content-Type: application/json

{
  "config": {
    "profile_schema": {
      "user": {
        "name": "",
        "timezone": "UTC",
        "new_field": "default_value"
      }
    }
  }
}
```

#### Schema Design

There's no enforced schema—profile is a JSON document you control. Recommended structure:

```json
{
  "user": {
    "identity": {"name": "Sarah", "age": 32, "location": "SF"},
    "personality": {"openness": 0.78, "communication_style": "direct"},
    "mental_state": {"mood": "calm", "stress_level": 0.3}
  },
  "companion": {
    "shared_stories": ["backstory_1", "why_i_love_jazz"],
    "relationship_goals": ["help_with_anxiety"],
    "rapport_score": 0.8
  },
  "relationship": {
    "recent_topics": ["promotion", "marathon_training"],
    "boundaries": ["no_medical_advice"],
    "milestones": ["first_vulnerability", "100_turns"]
  },
  "app": {
    "subscription": "premium",
    "onboarding_complete": true,
    "timezone": "America/Los_Angeles"
  }
}
```

#### Profile Operations

```python
rel = em.relationship(companion_id, user_id)

# GET - Retrieve entire profile
profile = await rel.profile_get()

# SET - Replace entire profile
await rel.profile_set({
    "user": {"name": "Sarah"},
    "app": {"tier": "premium"}
})

# PATCH - Merge changes (RFC 7396 JSON Merge Patch)
await rel.profile_patch({
    "user": {"mood": "happy"},      # Adds/updates user.mood
    "app": {"feature_x": True}      # Adds app.feature_x
})

# CLEAR - Delete entire profile
await rel.profile_clear()
```

**Merge semantics (PATCH):**
- `{"key": "value"}` — Sets or overwrites
- `{"key": null}` — Deletes the key
- Nested objects merge recursively
- Arrays are replaced entirely (not merged)

#### Profile Visibility

| Context | Visible? |
|---------|----------|
| Behaviors (`ctx.profile`) | Always |
| Webhook payloads | Always |
| AI system prompt | Opt-in (configure `include_profile_in_prompt`) |

```python
# Include profile in AI's system prompt for one relationship
await rel.config_patch({"include_profile_in_prompt": True})

# Or set a companion-level default for all relationships
await em.companions.update(
    companion_id,
    config={"include_profile_in_prompt": True}
)
```

Relationship config overrides the companion default.

---

### 3.3 Knowledge Base

Add documents, FAQs, and reference material that companions can search during conversations.

#### Upload Knowledge

```python
# Ingest a file
job = await em.knowledge.ingest(
    companion_id,
    file_path="product_manual.pdf"
)

# Wait for processing
await em.knowledge.wait(job["id"])

# Or ingest raw text
job = await em.knowledge.ingest(
    companion_id,
    content="Our return policy allows returns within 30 days...",
    key="return-policy"
)
```

Supported formats: PDF, JSONL, TXT, Markdown.

#### Search Knowledge

```python
results = await em.knowledge.search(
    companion_id,
    query="How do I reset my password?",
    max_results=5
)

for result in results["results"]:
    print(f"[{result['score']:.2f}] {result['content'][:100]}...")
```

#### Knowledge in Conversations

When knowledge is enabled, the companion automatically searches and includes relevant context:

```python
companion = await em.companions.create(
    name="Support Bot",
    config={
        "system_prompt": {"full_system_prompt": "You are a helpful support agent."},
        "knowledge": {
            "enabled": True,
            "max_results": 5,
            "min_score": 0.7
        }
    }
)
```

---

### 3.4 Tools & Secrets

Connect companions to external APIs using OpenAPI specifications and secure credential storage.

#### Create Secrets

Store API keys and credentials securely (encrypted at rest):

```python
# Create a secret
await em.secrets.create(
    secret_name="stripe_api_key",
    secret_value="sk_live_...",
    description="Stripe production API key"
)

# List secrets (values never exposed)
secrets = await em.secrets.list()
for s in secrets:
    print(f"{s['secret_name']}: {s['description']}")

# Delete a secret
await em.secrets.delete("stripe_api_key")
```

#### Upload OpenAPI Spec

Define available tools from an OpenAPI specification:

```python
openapi_spec = {
    "openapi": "3.0.0",
    "info": {"title": "Weather API", "version": "1.0.0"},
    "servers": [{"url": "https://api.weather.com"}],
    "paths": {
        "/current": {
            "get": {
                "operationId": "get_current_weather",
                "summary": "Get current weather for a location",
                "parameters": [
                    {
                        "name": "location",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {"200": {"description": "Weather data"}}
            }
        }
    }
}

# Upload spec with secrets mapping
result = await em.tools.upload(
    companion_id,
    spec_name="weather-api",
    openapi_spec=openapi_spec,
    secrets_config={
        "Authorization": "weather_api_key"  # Header → Secret name
    }
)
print(f"Spec ID: {result['spec_id']}")
```

#### Tools in Conversations

Enable tools layer in companion config:

```python
companion = await em.companions.create(
    name="Assistant",
    config={
        "system_prompt": {"full_system_prompt": "You are a helpful assistant."},
        "tools": {"enabled": True}
    }
)
```

The AI will automatically discover and use available tools when relevant.

---

### 3.5 WebSocket Protocol

For real-time applications using `rel.connect()`.

#### Event Types

| Event | Durable? | Description |
|-------|----------|-------------|
| `connected` | No | Connection established |
| `ack` | Yes | Message received, turn started |
| `status` | No | Processing stage update |
| `delta` | No | Streaming token |
| `message` | Yes | Complete assistant message |
| `proactive` | Yes | Companion-initiated message |
| `state_updated` | Yes | Profile/state changed |
| `cancelled` | Yes | Turn was cancelled |
| `error` | Yes | Error occurred |
| `heartbeat` | No | Keep-alive (every 30s) |

**Durable events** have a `seq` number and are replayable. **Ephemeral events** are not stored.

#### Event Flow

```
Client: {"type": "user_message", "client_message_id": "abc", "content": "Hello!"}
    │
    ├─► Server: {seq: 42, type: "ack", data: {client_message_id: "abc", turn_id: "..."}}
    │
    ├─► Server: {seq: null, type: "status", data: {stage: "thinking"}}
    │
    ├─► Server: {seq: null, type: "delta", data: {content: "Hi"}}
    ├─► Server: {seq: null, type: "delta", data: {content: " there"}}
    ├─► Server: {seq: null, type: "delta", data: {content: "!"}}
    │
    └─► Server: {seq: 43, type: "message", data: {content: "Hi there!", ...}}
```

#### Resume After Disconnect

```python
last_seq = load_from_storage()  # Your persistence

async with rel.connect(since_seq=last_seq) as ws:
    async for event in ws:
        if event.get("seq"):
            save_to_storage(event["seq"])  # Track progress
        handle(event)
```

Durable events are replayed from `since_seq`. Ephemeral events (deltas) are not replayed—if you reconnect mid-stream, you'll get the final `message` event.

#### Idempotency

```python
import uuid

async with rel.connect() as ws:
    msg_id = str(uuid.uuid4())

    # Safe to retry—server deduplicates by client_message_id
    await ws.send("Hello!", client_message_id=msg_id)
    await ws.send("Hello!", client_message_id=msg_id)  # Ignored, same ack returned
```

#### Cancel a Turn

```python
async with rel.connect() as ws:
    await ws.send("Tell me a very long story...")

    # User wants to interrupt
    await ws.cancel()

    # Server responds with {type: "cancelled", turn_id: "..."}
    # Now safe to send a new message
    await ws.send("Actually, just give me a summary.")
```

---

### 3.6 Voice Integration

Real-time voice conversations via `rel.voice()`.

#### Voice Configuration

```python
async with rel.voice(config={
    "voice_name": "sage",           # Voice to use
    "pipeline_type": "openai-realtime",  # or "stt-llm-tts"
}) as voice:
    async for event in voice:
        handle(event)
```

#### Pipeline Types

| Pipeline | Description | Latency | Cost |
|----------|-------------|---------|------|
| `openai-realtime` | OpenAI's native realtime API | Lowest | Higher |
| `stt-llm-tts` | Separate STT → LLM → TTS | Higher | Lower, more control |

#### STT-LLM-TTS Configuration

```python
async with rel.voice(config={
    "pipeline_type": "stt-llm-tts",
    "stt_provider": "deepgram",      # openai, deepgram, ultravox, cartesia
    "llm_provider": "claude-sonnet-4",  # Any supported LLM
    "tts_provider": "elevenlabs",    # openai, elevenlabs, cartesia
    "voice_name": "Sarah",           # Provider-specific voice
    "temperature": 0.7,
}) as voice:
    async for event in voice:
        handle(event)
```

#### Available Voices

**OpenAI:** `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`

**ElevenLabs:** `Sarah`, `George`, `Callum`, `Charlotte`, `Matilda`, `Will`

**Cartesia:** `Sophie`, `Savannah`, `Brooke`, `Griffin`, `Zia`, `Carson`, `Wise Lady`, `Ethan`

#### Audio Format

| Pipeline | Direction | Sample Rate | Format |
|----------|-----------|-------------|--------|
| OpenAI Realtime | Both | 24kHz | PCM Int16, mono |
| STT-LLM-TTS | Client → Server | 16kHz | PCM Int16, mono |
| STT-LLM-TTS | Server → Client | 24kHz | PCM Int16, mono |

---

### 3.7 Context Orchestrator

The layered context engine assembles the AI's prompt from multiple sources.

#### Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    ASSEMBLED PROMPT                              │
├─────────────────────────────────────────────────────────────────┤
│  Core System Prompt                                              │
│  + Priority Behavior Injections                                  │
│  + Memory Context (if retrieved)                                 │
│  + Knowledge Context (if relevant)                               │
│  + Profile (if include_profile_in_prompt=true)                   │
│  + Session State (if in session)                                 │
│  + Recent Messages                                               │
│  + Current User Message                                          │
└─────────────────────────────────────────────────────────────────┘
```

#### Layer Configuration

```python
companion = await em.companions.create(
    name="Assistant",
    config={
        "system_prompt": {
            "full_system_prompt": "You are a helpful assistant."
        },
        "memory": {
            "enabled": True,
            "top_k": 15,
            "min_saliency": 0.2,
            "recency": 0.995
        },
        "knowledge": {
            "enabled": True,
            "max_results": 5
        },
        "behaviors": {
            "enabled": True
        },
        "tools": {
            "enabled": True
        }
    }
)
```

#### Context Mode

Two modes available:

| Mode | Description |
|------|-------------|
| `layered` | Full context engine with memory, knowledge, behaviors (default) |
| `legacy` | Original v1 behavior without context engine |

```python
# Set at companion level
companion = await em.companions.create(
    name="Assistant",
    config={"context_mode": "layered"}  # default
)

# Or override at relationship level (before first message)
await rel.config_patch({"context_mode": "legacy"})
```

**Note:** Context mode is locked after the first message in a relationship.

---

### 3.8 Sessions

Explicit bounded interactions for billing, reporting, or context isolation.

#### Session Lifecycle

```python
rel = em.relationship(companion_id, user_id)

# Start session
session = await rel.session_start(
    type="coaching",     # Custom type for your billing/reporting
    isolated=False       # True = no state changes persist
)

# Chat within session
response = await session.send("Let's begin")
async for chunk in session.stream("How should we start?"):
    print(chunk)

# Update session state (temporary, cleared on end)
await session.state_patch({"current_step": 2})

# End session
result = await session.end()
print(result["summary"])  # AI-generated summary
```

#### Isolated Sessions

| Aspect | `isolated=False` | `isolated=True` |
|--------|------------------|-----------------|
| Prior message history | Loaded | Not loaded |
| Memory read | Yes | Yes |
| Memory write | Yes | No |
| Profile changes | Allowed | Blocked |
| After session ends | Messages in relationship | Messages stay in session only |

Use isolated sessions for: therapy notes, legal compliance, sealed records.

#### Session Queries

```python
# Get active session
active = await rel.session_active()

# List all sessions
sessions = await rel.session_list(limit=10)

# Get specific session
session = await rel.session_get(session_id)
```

---

### 3.9 Idempotency

All message operations support idempotency for safe retries.

#### REST

```python
import uuid

response = await rel.send(
    "Hello!",
    idempotency_key=str(uuid.uuid4())
)

# Safe to retry with same key—returns cached response
response = await rel.send(
    "Hello!",
    idempotency_key=same_key  # Same response returned
)
```

#### WebSocket

```python
async with rel.connect() as ws:
    msg_id = str(uuid.uuid4())

    # SDK handles client_message_id automatically
    await ws.send("Hello!", client_message_id=msg_id)

    # On reconnect, safe to resend pending messages
    # Server deduplicates by client_message_id
```

| Transport | Idempotency Key | Conflict Behavior |
|-----------|-----------------|-------------------|
| REST | `Idempotency-Key` header | 409 if key reused with different content |
| WebSocket | `client_message_id` field | Error event if reused with different content |

---

### 3.10 Configuration Hierarchy

Configuration cascades from companion → relationship → turn:

```
Turn Config (highest priority)
    ↓ merges with
Relationship Config
    ↓ merges with
Companion Config (base)
    ↓
════════════════════════
Resolved Config
```

```python
# Companion-level defaults
companion = await em.companions.create(
    name="Coach",
    config={
        "system_prompt": {"full_system_prompt": "You are a coach."},
        "memory": {"enabled": True, "top_k": 10}
    }
)

# Relationship-level overrides
rel = em.relationship(companion_id, user_id)
await rel.config_patch({
    "memory": {"top_k": 20}  # Override for this user
})

# Turn-level overrides
response = await rel.send(
    "Hello!",
    config={"inference": {"temperature": 0.9}}  # Just for this message
)
```

---

## 4. API Reference

Base URL: `https://api.emotionmachine.ai`

All endpoints require authentication via Bearer token:

```bash
Authorization: Bearer emk_live_a1b2c3d4e5f6.your_secret_here
```

---

### 4.1 Companions

#### List Companions

```http
GET /v1/companions
```

**Response** `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Customer Support Agent",
    "description": "Handles customer inquiries",
    "config": { ... },
    "created_at": "2024-01-15T10:30:00Z",
    "project_id": "123e4567-e89b-12d3-a456-426614174000"
  }
]
```

---

#### Create Companion

```http
POST /v1/companions
Content-Type: application/json

{
  "name": "Customer Support Agent",
  "description": "Handles customer inquiries",
  "config": {
    "system_prompt": {
      "full_system_prompt": "You are a helpful customer support agent..."
    },
    "inference": {
      "model": "openai-gpt4o-mini",
      "temperature": 0.7
    },
    "memory": { "enabled": true },
    "knowledge": { "enabled": true },
    "behaviors": { "enabled": true },
    "include_profile_in_prompt": true,
    "profile_schema": {
      "user": { "name": "", "tier": "free" }
    }
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Companion name (1-100 chars) |
| description | string | No | Description (max 500 chars) |
| config | object | No | Companion configuration |

**Config Fields:**

| Field | Type | Description |
|-------|------|-------------|
| system_prompt | object | System prompt configuration |
| inference | object | LLM model and parameters |
| memory | object | Memory settings (version, top_k, etc.) |
| knowledge | object | Knowledge base settings |
| behaviors | object | Behavior execution settings |
| context | object | Context assembly settings |
| include_profile_in_prompt | boolean | Default profile-in-prompt behavior for new/existing relationships unless overridden |
| profile_schema | object | Default structure/values for user profiles (see Section 3.2) |

**Context Configuration:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| context.message_limit | int | 200 | Maximum messages loaded into context per turn. Minimum: 10. |

```python
companion = await em.companions.create(
    name="Assistant",
    config={
        "context": {
            "message_limit": 100  # Load last 100 messages
        }
    }
)
```

> **Note:** Higher values provide more conversation context but consume more tokens. Consider your model's context window when setting this value.

**Response** `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Customer Support Agent",
  "description": "Handles customer inquiries",
  "config": { ... },
  "created_at": "2024-01-15T10:30:00Z",
  "project_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

---

#### Get Companion

```http
GET /v1/companions/{companion_id}
```

**Response** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Customer Support Agent",
  "config": { ... },
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

#### Update Companion

```http
PATCH /v1/companions/{companion_id}
Content-Type: application/json

{
  "name": "Updated Agent Name",
  "config": {
    "system_prompt": {
      "full_system_prompt": "Updated system prompt..."
    }
  }
}
```

**Response** `200 OK`

---

#### Intro Message Automation (WebSocket First Message)

Use companion config to enable/disable automatic intro messages sent when a text WebSocket connection starts.

```http
PATCH /v1/companions/{companion_id}
Content-Type: application/json

{
  "config": {
    "intro_message": {
      "enabled": true,
      "text": "Hi, how are you?",
      "send_once_per_relationship": true
    }
  }
}
```

Disable intro message:

```http
PATCH /v1/companions/{companion_id}
Content-Type: application/json

{
  "config": {
    "intro_message": {
      "enabled": false
    }
  }
}
```

Bulk update all companions in a project:

```bash
curl -sS "$EM_API_BASE_URL/v1/companions" \
  -H "Authorization: Bearer $EM_API_KEY" \
| jq -r '.[].id' \
| while read -r cid; do
    curl -sS -X PATCH "$EM_API_BASE_URL/v1/companions/$cid" \
      -H "Authorization: Bearer $EM_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"config":{"intro_message":{"enabled":true,"text":"Hi, how are you?"}}}' >/dev/null
    echo "updated $cid"
  done
```

Notes:
- `config` is deep-merged on update, so patching only `config.intro_message` does not wipe other config fields.
- Intro message is sent on WebSocket connect only when the relationship has no messages.
- If `text` is empty, the server fallback is `"Hi, how are you?"`.

---

#### Delete Companion

```http
DELETE /v1/companions/{companion_id}
```

**Response** `204 No Content`

---

### 4.2 Relationships

#### Ensure Relationship Exists

Creates relationship if it doesn't exist, returns existing if it does (idempotent).

```http
PUT /v2/companions/{companion_id}/relationships/{user_id}
```

| Parameter | Type | Description |
|-----------|------|-------------|
| companion_id | uuid | Companion ID |
| user_id | string | Your user identifier (URL-safe, max 128 chars) |

**Response** `200 OK` or `201 Created`

```json
{
  "id": "rel_123e4567-e89b-12d3-a456-426614174000",
  "companion_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user_123",
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

#### Get Relationship by Companion + User

```http
GET /v2/companions/{companion_id}/relationships/{user_id}
```

**Response** `200 OK`

```json
{
  "id": "rel_123e4567-e89b-12d3-a456-426614174000",
  "companion_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user_123",
  "profile": { ... },
  "config": { ... },
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Response** `404 Not Found` if relationship doesn't exist.

---

#### Get Relationship by ID

```http
GET /v2/relationships/{relationship_id}
```

---

#### List Relationships

```http
GET /v2/companions/{companion_id}/relationships?limit=50&cursor=...
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Results per page (1-200) |
| cursor | string | — | Pagination cursor |

**Response** `200 OK`

```json
{
  "items": [
    {
      "id": "rel_123...",
      "user_id": "user_123",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "next_cursor": "eyJpZCI6..."
}
```

---

#### Delete Relationship

```http
DELETE /v2/relationships/{relationship_id}
```

**Response** `204 No Content`

---

### 4.3 Messages

#### List Messages (By Relationship ID)

```http
GET /v2/relationships/{relationship_id}/messages?limit=50&before_seq=123
```

Returns sequenced relationship messages ordered oldest -> newest.

Proactive messages are included by default. There is no `include_proactive` query parameter.

| Query | Type | Default | Description |
|-------|------|---------|-------------|
| limit | int | 50 | Number of messages to return (1-500) |
| before_seq | int | — | Backward pagination anchor (`seq < before_seq`) |
| after_seq | int | — | Forward pagination anchor (`seq > after_seq`) |
| session_id | uuid | — | Optional session filter (must belong to this relationship) |

`before_seq` and `after_seq` are mutually exclusive.

**Response** `200 OK`

```json
{
  "relationship_id": "rel_123...",
  "messages": [
    {
      "id": "msg_1...",
      "relationship_id": "rel_123...",
      "session_id": "4af4f87e-b389-42e4-9607-0e7ad8f53797",
      "seq": 120,
      "role": "user",
      "content": "Hey there",
      "created_at": "2026-03-03T23:10:00Z",
      "build_ms": null,
      "input_modality": "text",
      "is_proactive": false,
      "delivery_status": null
    },
    {
      "id": "msg_2...",
      "relationship_id": "rel_123...",
      "session_id": "4af4f87e-b389-42e4-9607-0e7ad8f53797",
      "seq": 121,
      "role": "assistant",
      "content": "Hi, how are you?",
      "created_at": "2026-03-03T23:10:01Z",
      "build_ms": 642,
      "input_modality": "text",
      "is_proactive": false,
      "delivery_status": null
    }
  ],
  "limit": 50,
  "has_more": true,
  "oldest_seq": 120,
  "newest_seq": 121
}
```

---

#### List Messages (By Companion + User)

```http
GET /v2/companions/{companion_id}/relationships/{user_id}/messages?limit=50
```

Resolves the relationship from `{companion_id}` + external `{user_id}`, then returns the same `MessageListResponse` shape as above.

Proactive messages are included by default. There is no `include_proactive` query parameter.

Returns `404 Not Found` if the relationship does not exist.

---

#### Send Message (REST)

Composite endpoint: ensures relationship exists and sends message in one call.

```http
POST /v2/companions/{companion_id}/relationships/{user_id}/messages
Content-Type: application/json
Idempotency-Key: optional-uuid

{
  "content": "Hello!",
  "session_id": null,
  "config": {
    "inference": { "temperature": 0.7 }
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| content | string | Yes | User message (1-4000 chars) |
| session_id | uuid | No | Session to chat within |
| config | object | No | Turn-level config overrides |
| image_ids | uuid[] | No | Image IDs for context |

**Response** `200 OK`

```json
{
  "relationship_id": "rel_123...",
  "message": {
    "id": "msg_456...",
    "role": "assistant",
    "content": "Hello! How can I help you today?",
    "created_at": "2024-01-15T10:30:05Z"
  }
}
```

---

#### Send Message (Streaming)

Same endpoint, different Accept header:

```http
POST /v2/companions/{companion_id}/relationships/{user_id}/messages
Content-Type: application/json
Accept: text/event-stream

{
  "content": "Tell me a story"
}
```

**Response** `200 OK` (Server-Sent Events)

```
event: ack
data: {"relationship_id": "rel_123...", "turn_id": "turn_456..."}

event: status
data: {"stage": "thinking", "phase": "start"}

event: delta
data: {"content": "Once"}

event: delta
data: {"content": " upon"}

event: delta
data: {"content": " a time..."}

event: message
data: {"id": "msg_789...", "content": "Once upon a time...", ...}

event: done
data: {"relationship_id": "rel_123..."}
```

---

#### Send Message (By Relationship ID)

If you already have the relationship ID:

```http
POST /v2/relationships/{relationship_id}/messages
Content-Type: application/json

{
  "content": "Hello!"
}
```

---

### 4.4 Profile

#### Get Profile

```http
GET /v2/relationships/{relationship_id}/profile
```

**Response** `200 OK`

```json
{
  "user": {
    "name": "Sarah",
    "age": 28
  },
  "app": {
    "subscription": "premium"
  }
}
```

---

#### Set Profile (Replace)

```http
PUT /v2/relationships/{relationship_id}/profile
Content-Type: application/json

{
  "user": {
    "name": "Sarah",
    "age": 28
  }
}
```

**Response** `200 OK`

---

#### Patch Profile (Merge)

Uses RFC 7396 JSON Merge Patch semantics.

```http
PATCH /v2/relationships/{relationship_id}/profile
Content-Type: application/json

{
  "user": {
    "mood": "happy"
  },
  "new_section": {
    "key": "value"
  }
}
```

**Response** `200 OK`

---

#### Clear Profile

```http
DELETE /v2/relationships/{relationship_id}/profile
```

**Response** `204 No Content`

---

### 4.5 Configuration

#### Get Relationship Config

```http
GET /v2/relationships/{relationship_id}/config
```

**Response** `200 OK`

```json
{
  "context_mode": "layered",
  "include_profile_in_prompt": false,
  "memory": {
    "top_k": 15
  }
}
```

---

#### Get Resolved Config

Returns the merged config (companion + relationship).

```http
GET /v2/relationships/{relationship_id}/config/resolved
```

**Response** `200 OK`

```json
{
  "config": {
    "system_prompt": { "full_system_prompt": "..." },
    "inference": {
      "model": "openai-gpt4o-mini",
      "temperature": 0.7
    },
    "memory": { "enabled": true, "top_k": 20 },
    "include_profile_in_prompt": true
  },
  "companion_config": {
    "system_prompt": { "full_system_prompt": "..." },
    "inference": {
      "model": "openai-gpt4o-mini",
      "temperature": 0.7
    },
    "memory": { "enabled": true, "top_k": 15 },
    "include_profile_in_prompt": false
  },
  "relationship_overrides": {
    "memory": { "top_k": 20 },
    "include_profile_in_prompt": true
  }
}
```

---

#### Patch Config

```http
PATCH /v2/relationships/{relationship_id}/config
Content-Type: application/json

{
  "memory": {
    "top_k": 20
  }
}
```

**Response** `200 OK`

---

### 4.6 Memory (Scratchpad)

Memory v2 (scratchpad) provides direct CRUD access to memory entries. The AI can also read/write memories during conversations when `memory.version: 2` is configured.

#### List Memory Entries

```http
GET /v2/relationships/{relationship_id}/memory
```

**Response** `200 OK`

```json
{
  "entries": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "content": "User prefers morning meetings",
      "type": "preference",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ],
  "count": 1,
  "max_entries": 100
}
```

---

#### Get Memory Entry

```http
GET /v2/relationships/{relationship_id}/memory/{entry_id}
```

**Response** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "User prefers morning meetings",
  "type": "preference",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

#### Create Memory Entry

```http
POST /v2/relationships/{relationship_id}/memory
Content-Type: application/json

{
  "content": "User prefers morning meetings",
  "type": "preference"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| content | string | Yes | Memory content (1-2000 chars) |
| type | string | No | Entry type: identity, preference, goal, event, relationship, other |

**Response** `201 Created`

---

#### Update Memory Entry

```http
PATCH /v2/relationships/{relationship_id}/memory/{entry_id}
Content-Type: application/json

{
  "content": "User now prefers afternoon meetings",
  "type": "preference"
}
```

**Response** `200 OK`

---

#### Delete Memory Entry

```http
DELETE /v2/relationships/{relationship_id}/memory/{entry_id}
```

**Response** `204 No Content`

---

#### Clear All Memory

```http
DELETE /v2/relationships/{relationship_id}/memory
```

**Response** `204 No Content`

---

### 4.7 Sessions

#### Start Session

```http
POST /v2/relationships/{relationship_id}/sessions
Content-Type: application/json

{
  "type": "coaching",
  "isolated": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| type | string | null | Custom type for billing/reporting |
| isolated | boolean | false | If true, no state changes persist |

**Response** `201 Created`

```json
{
  "id": "sess_123...",
  "relationship_id": "rel_456...",
  "type": "coaching",
  "status": "active",
  "isolated": false,
  "state": {},
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

#### Get Session

```http
GET /v2/sessions/{session_id}
```

---

#### List Sessions

```http
GET /v2/relationships/{relationship_id}/sessions?limit=10&cursor=...
```

---

#### Get Active Session

```http
GET /v2/relationships/{relationship_id}/sessions/active
```

Returns `200 OK` with session, or `404 Not Found` if no active session.

---

#### End Session

```http
POST /v2/sessions/{session_id}/end
```

**Response** `200 OK`

```json
{
  "id": "sess_123...",
  "status": "ended",
  "summary": "AI-generated summary of the session...",
  "ended_at": "2024-01-15T11:30:00Z"
}
```

---

#### Update Session State

```http
PATCH /v2/sessions/{session_id}/state
Content-Type: application/json

{
  "changes": {
    "current_step": 3,
    "notes": "User mentioned anxiety"
  }
}
```

The `changes` wrapper is required; its contents are merged into the session state.

**Response** `200 OK` — returns the full session object (same shape as `GET /v2/sessions/{id}`).

---

### 4.8 Inbox (Proactive Messages)

#### Check Inbox

```http
GET /v2/relationships/{relationship_id}/inbox?limit=20&include_delivered=false
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Max messages to return (1-100) |
| include_delivered | boolean | false | Include already-delivered messages |

**Response** `200 OK`

```json
{
  "messages": [
    {
      "id": "msg_123...",
      "seq": 42,
      "content": "Good morning! How are you feeling today?",
      "source_behavior_key": "daily_checkin",
      "delivery_status": "pending",
      "created_at": "2024-01-15T09:00:00Z",
      "expires_at": "2024-01-16T09:00:00Z"
    }
  ],
  "count": 1
}
```

---

#### Acknowledge Messages

```http
POST /v2/relationships/{relationship_id}/inbox/ack
Content-Type: application/json

{
  "message_ids": ["msg_123...", "msg_456..."]
}
```

**Response** `200 OK`

```json
{
  "acknowledged": 2,
  "message_ids": ["msg_123...", "msg_456..."]
}
```

---

### 4.9 Behaviors

#### List Behaviors

```http
GET /v2/companions/{companion_id}/behaviors
```

**Response** `200 OK`

```json
{
  "companion_id": "550e8400-...",
  "behaviors": [
    {
      "link_id": "770e8400-...",
      "companion_id": "550e8400-...",
      "relationship_id": null,
      "behavior_id": "880e8400-...",
      "behavior_key": "mood_tracker",
      "behavior_name": "mood_tracker",
      "behavior_description": "Tracks user mood on every message",
      "has_source_code": true,
      "version": 1,
      "triggers": ["always"],
      "priority": true,
      "isolated": false,
      "enabled": true,
      "classifier_eligible": true,
      "classifier_hint": null,
      "webhook_url": null,
      "params": {}
    }
  ],
  "total": 1
}
```

---

#### Create Behavior

```http
POST /v2/companions/{companion_id}/behaviors
Content-Type: application/json

{
  "behavior_key": "mood_tracker",
  "triggers": ["always"],
  "priority": true,
  "webhook_url": "https://yourapp.com/hooks/behavior",
  "webhook_secret": "whsec_..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| behavior_key | string | Yes | Key of the behavior to link. If no behavior with this key exists in the project, an empty one is created. |
| triggers | string[] | No | Trigger shorthand strings: `"always"`, `"every:5"`, `"idle:30"`, `"cron:0 0 * * 0"` |
| priority | boolean | No | Sync (true, runs before the LLM and can inject prompt blocks) or async (false) |
| isolated | boolean | No | Run in isolated container (slower, more secure) |
| enabled | boolean | No | Default true |
| classifier_eligible | boolean | No | Whether the intent classifier can select this behavior |
| classifier_hint | string | No | Hint for the classifier |
| webhook_url | string | No | URL called after the behavior completes |
| webhook_secret | string | No | HMAC secret for webhook signatures |
| params | object | No | Custom parameters passed to the behavior |

Source code is **not** set here. After linking, upload the code with
`PATCH /v2/companions/{companion_id}/behaviors/{behavior_key}/definition` (below).

**Response** `201 Created` — returns the behavior link (same shape as list items above).

#### Create a Fresh Behavior Definition

```http
POST /v2/companions/{companion_id}/behavior-definitions
Content-Type: application/json

{
  "key": "relationship_update_step06_v1",
  "name": "Relationship update v1",
  "source_code": "async def execute(ctx): return None"
}
```

This creates a new project-scoped definition and never links or updates an
existing definition. An existing project key returns `409 Conflict`.

#### Switch a Behavior Definition

```http
POST /v2/companions/{companion_id}/behaviors/{behavior_key}/switch
Content-Type: application/json

{
  "behavior_key": "relationship_update",
  "new_behavior_id": "...",
  "links": [
    {"link_id": "...", "relationship_id": null, "expected_behavior_id": "..."},
    {"link_id": "...", "relationship_id": "...", "expected_behavior_id": "..."}
  ]
}
```

This endpoint currently returns `503 Service Unavailable` and performs no
mutation. The runtime has no distributed execution gate, in-flight job drain,
or cross-worker cache invalidation contract. The repository's transactional
compare-and-swap is not a live cutover API until those gates are implemented.

---

#### Update Behavior Definition (source code)

```http
PATCH /v2/companions/{companion_id}/behaviors/{behavior_key}/definition
Content-Type: application/json

{
  "source_code": "async def execute(ctx):\n    if 'anxious' in ctx.message.lower():\n        ctx.profile.set('user.mood', 'anxious')\n        return 'User seems anxious. Be supportive.'\n    return None",
  "description": "Tracks user mood on every message",
  "dependencies": [],
  "timeout_seconds": 60,
  "block_network": false
}
```

All fields optional. This updates the behavior itself (shared across links), not the link configuration.

**Response** `200 OK`

---

#### Get Behavior

```http
GET /v2/companions/{companion_id}/behaviors/{behavior_key}
```

---

#### Update Behavior

```http
PATCH /v2/companions/{companion_id}/behaviors/{behavior_key}
Content-Type: application/json

{
  "triggers": ["every:5"],
  "enabled": false
}
```

---

#### Delete Behavior

```http
DELETE /v2/companions/{companion_id}/behaviors/{behavior_key}
```

**Response** `204 No Content`

---

#### Trigger Behavior (API)

```http
POST /v2/relationships/{relationship_id}/behaviors/{behavior_key}/trigger
Content-Type: application/json

{
  "context": {
    "custom_data": "value"
  }
}
```

**Response** `200 OK`

```json
{
  "job_id": "job_123...",
  "status": "queued",
  "behavior_key": "mood_tracker"
}
```

---

#### Relationship-Scoped Behavior Overrides

Companion-level links are defaults. A relationship can override them (same body
shapes as the companion-scoped routes; an override has `relationship_id` set):

```http
GET    /v2/relationships/{relationship_id}/behaviors
POST   /v2/relationships/{relationship_id}/behaviors
GET    /v2/relationships/{relationship_id}/behaviors/{behavior_key}
PATCH  /v2/relationships/{relationship_id}/behaviors/{behavior_key}
DELETE /v2/relationships/{relationship_id}/behaviors/{behavior_key}
```

---

### 4.10 WebSocket

#### Get WebSocket Token

Exchange API key for a short-lived JWT token.

```http
POST /v2/companions/{companion_id}/relationships/{user_id}/ws-token
```

**Response** `200 OK`

```json
{
  "token": "eyJhbGc...",
  "relationship_id": "rel_123...",
  "expires_in": 3600
}
```

---

#### Connect WebSocket

```
WS /v2/companions/{companion_id}/relationships/{user_id}/connect
```

Or by relationship ID:

```
WS /v2/relationships/{relationship_id}/connect
```

**Authentication:**

Token can be provided via two methods (header takes precedence if both are provided):

| Method | Header/Parameter | Use Case |
|--------|-----------------|----------|
| **Authorization Header** (preferred) | `Authorization: Bearer <token>` | Mobile/native clients |
| Query Parameter (fallback) | `?token=<token>` | Browser clients (cannot set WS headers) |

**Example (Mobile/Native):**
```
WS /v2/companions/{id}/relationships/{user_id}/connect
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Example (Browser):**
```
WS /v2/companions/{id}/relationships/{user_id}/connect?token=eyJhbGciOiJIUzI1NiIs...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| token | string | JWT from ws-token endpoint (query param, optional if using header) |
| since_seq | int | Optional: replay events from this sequence |

**Client → Server Messages:**

```json
{"type": "user_message", "client_message_id": "abc123", "content": "Hello!"}
{"type": "ping"}
{"type": "cancel"}
{"type": "refresh_token"}
```

**Server → Client Events:**

```json
{"seq": 42, "type": "ack", "data": {"client_message_id": "abc123", "turn_id": "..."}}
{"seq": null, "type": "status", "data": {"stage": "thinking"}}
{"seq": null, "type": "delta", "data": {"content": "Hi"}}
{"seq": 43, "type": "message", "data": {"content": "Hi there!", ...}}
{"seq": 44, "type": "proactive", "data": {"content": "Hey! Just checking in."}}
{"seq": null, "type": "heartbeat", "data": {}}
{"type": "error", "data": {"code": "...", "message": "..."}}
```

**Close Codes:**

| Code | Meaning |
|------|---------|
| 1000 | Normal close |
| 1012 | Server restart |
| 4001 | Invalid token |
| 4002 | Token expired |
| 4004 | Relationship not found |

---

### 4.11 Voice

#### Get Voice Token

```http
POST /v2/companions/{companion_id}/relationships/{user_id}/voice/token
Content-Type: application/json

{
  "config": {
    "pipeline_type": "openai-realtime",
    "voice_name": "sage"
  }
}
```

**Response** `200 OK`

```json
{
  "token": "eyJhbGc...",
  "ws_url": "wss://api.emotionmachine.ai/v2/...",
  "relationship_id": "rel_123...",
  "expires_in": 3600
}
```

---

#### Connect Voice WebSocket

```
WS /v2/companions/{companion_id}/relationships/{user_id}/voice/connect?token=...
```

Relationship-ID variants also exist:

```
POST /v2/relationships/{relationship_id}/voice/token
WS   /v2/relationships/{relationship_id}/voice/connect?token=...
```

Audio format: PCM Int16, mono. Input 16kHz, output 24kHz (STT-LLM-TTS pipeline).

---

### 4.12 Knowledge (v1)

Knowledge endpoints use v1 prefix.

Related: `POST /v1/companions/{companion_id}/core-memories` seeds core memories for a
relationship (`{"external_user_id": ..., "memories": [...]}`).

#### Upload Knowledge Asset (dashboard API)

Raw file uploads use the dashboard API with a Clerk session token, not a project API key:

```http
POST /api/companions/{companion_id}/knowledge-assets
Content-Type: multipart/form-data

file: <binary>
```

With a project API key, use `POST /v1/companions/{id}/knowledge` (below) to ingest
text or JSON content directly.

---

#### Ingest Knowledge

```http
POST /v1/companions/{companion_id}/knowledge
Content-Type: application/json

{
  "type": "text",
  "content": "Our return policy allows...",
  "key": "return-policy"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | string | Yes | `text`, `url`, or `asset` |
| content | string | Conditional | Required for `text` type |
| key | string | No | Identifier for the item |
| asset_id | uuid | Conditional | Required for `asset` type |

**Response** `202 Accepted`

---

#### Search Knowledge

```http
POST /v1/companions/{companion_id}/knowledge/search
Content-Type: application/json

{
  "query": "How do I reset my password?",
  "max_results": 5
}
```

**Response** `200 OK`

```json
{
  "results": [
    {
      "content": "To reset your password, go to Settings...",
      "score": 0.92,
      "metadata": { "key": "password-reset" }
    }
  ]
}
```

---

#### Get Knowledge Job Status

```http
GET /v1/knowledge-jobs/{job_id}
```

---

### 4.13 Tools (v1)

Tools endpoints use v1 prefix.

#### Upload Tool Spec

```http
POST /v1/companions/{companion_id}/tools
Content-Type: application/json

{
  "spec_name": "weather-api",
  "openapi_spec": { ... },
  "secrets_config": {
    "Authorization": "weather_api_key"
  }
}
```

**Response** `201 Created`

```json
{
  "spec_id": "spec_123...",
  "dispatched": true,
  "request_id": "req_456..."
}
```

---

#### List Tool Specs

```http
GET /v1/companions/{companion_id}/tools
```

---

#### Get Tool Spec

```http
GET /v1/companions/{companion_id}/tools/{spec_id}
```

---

#### Update Tool Secrets Config

```http
PATCH /v1/companions/{companion_id}/tools/{spec_id}
Content-Type: application/json

{
  "secrets_config": {
    "Authorization": "new_api_key"
  }
}
```

---

#### Delete Tool Spec

```http
DELETE /v1/companions/{companion_id}/tools/{spec_id}
```

---

### 4.14 Secrets (v1)

Secrets endpoints use v1 prefix.

#### Create/Update Secret

```http
POST /v1/secrets
Content-Type: application/json

{
  "secret_name": "stripe_api_key",
  "secret_value": "sk_live_...",
  "description": "Stripe production API key"
}
```

**Response** `201 Created`

```json
{
  "id": "secret_123...",
  "secret_name": "stripe_api_key",
  "description": "Stripe production API key",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

#### List Secrets

Returns metadata only—values are never exposed.

```http
GET /v1/secrets
```

**Response** `200 OK`

```json
[
  {
    "id": "secret_123...",
    "secret_name": "stripe_api_key",
    "description": "Stripe production API key",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  }
]
```

---

#### Delete Secret

```http
DELETE /v1/secrets/{secret_name}
```

**Response** `204 No Content`

---

### 4.15 Summaries (Conversation History)

Summaries provide automatic summarization of conversation history. When a relationship's message count crosses the configured `message_limit` threshold (default 200), the system automatically generates an incremental summary of the conversation.

**How it works:**
- At 200 messages → v1 summary (covers messages 1-200)
- At 400 messages → v2 summary (previous summary + messages 201-400)
- At 600 messages → v3 summary (previous summary + messages 401-600)
- And so on...

Summaries are automatically injected into the LLM context between memory and recent messages, providing continuity for long conversations.

#### List Summaries

```http
GET /v2/companions/{companion_id}/relationships/{user_id}/summaries?limit=10
```

**Response** `200 OK`

```json
{
  "items": [
    {
      "id": "sum_123...",
      "relationship_id": "rel_456...",
      "content": "The user Sarah discussed her career goals...",
      "version": 2,
      "messages_start": 201,
      "messages_end": 400,
      "message_count": 400,
      "model": "google/gemini-2.0-flash-001",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 2
}
```

---

#### Get Latest Summary

```http
GET /v2/companions/{companion_id}/relationships/{user_id}/summaries/latest
```

**Response** `200 OK`

```json
{
  "id": "sum_123...",
  "relationship_id": "rel_456...",
  "content": "The user Sarah discussed her career goals...",
  "version": 2,
  "messages_start": 201,
  "messages_end": 400,
  "message_count": 400,
  "model": "google/gemini-2.0-flash-001",
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Response** `404 Not Found` — No summary exists yet

---

#### Trigger Summarization (Manual)

Manually trigger summarization if the relationship has enough unsummarized messages. Useful for testing or forcing a summary before the automatic threshold.

```http
POST /v2/companions/{companion_id}/relationships/{user_id}/summaries/trigger
```

**Response** `200 OK` (when triggered)

```json
{
  "triggered": true,
  "message": "Summarization job dispatched for version 1",
  "version": 1,
  "messages_start": 1,
  "messages_end": 200
}
```

**Response** `200 OK` (when not enough messages)

```json
{
  "triggered": false,
  "message": "Not enough new messages to summarize. Current: 150, last summarized: 0, threshold: 200"
}
```

---

### 4.16 Error Responses

REST errors use FastAPI's standard envelope:

```json
{
  "detail": "Relationship 660e8400-... not found"
}
```

Validation errors (`422`) return FastAPI's standard `detail` array with the failing fields.

#### HTTP Status Codes

| Status | Meaning |
|--------|---------|
| 400 | Bad Request — Invalid parameters |
| 401 | Unauthorized — Invalid or missing API key |
| 404 | Not Found — Resource doesn't exist |
| 409 | Conflict — Turn in progress, version mismatch, or idempotency conflict |
| 422 | Unprocessable Entity — Request body failed validation |
| 500 | Server Error — Internal error |

#### WebSocket Error Codes

Structured error codes exist only on the WebSocket protocol (sent as `error` events):

| Code | Description |
|------|-------------|
| `invalid_seq` | Requested `since_seq` not found |

---
