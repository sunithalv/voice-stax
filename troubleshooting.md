# VoiceStax Troubleshooting Guide

This is a working engineering log of issues encountered while developing and testing VoiceStax and its examples. It records observed symptoms, diagnostic evidence, suspected or confirmed causes, changes made, and test results.

## Scope and status

- **Core voice pipeline:** browser audio, WebSockets, VAD, STT, LLM orchestration, TTS, interruptions, session lifecycle, and latency.
- **RAG example:** retrieval, small-talk routing, grounding, policy completeness, and web-search handling. These entries apply to the RAG example/provider and may not apply to every VoiceStax application.
- **Historical entries:** a fix documented here describes the change recorded at the time. Re-test it against the current code before treating it as a regression test or a guaranteed fix.
- **Evidence standard:** distinguish confirmed root causes from hypotheses. Keep measured results tied to the test setup; do not treat targets or estimates as universal benchmarks.

For each issue, record the symptom, evidence/logs, root cause (or current hypothesis), change made, verification steps, and any trade-offs. Avoid including API keys, tokens, personal data, or complete production payloads in logs.

---

## Table of Contents

1. [Greeting interrupted by false barge-in](#1-greeting-interruption-false-barge-in)
2. [High RAG lookup latency](#2-high-rag-lookup-latency)
3. [Small talk not detected](#3-small-talk-not-detected)
4. [Small-talk queries slow](#4-small-talk-queries-slow)
5. [Incomplete RAG responses](#5-incomplete-rag-responses)
6. [Missing critical safety information](#6-missing-critical-safety-information)
7. [Unreliable web-search results](#7-unreliable-web-search-results)
8. [Slow end-of-speech detection](#8-end-of-speech-detection-slow)
9. [Missing logger import](#9-logger-import-missing)
10. [Policy details omitted from responses](#10-agent-response-omits-policy-details-timeframes-steps-warnings)
11. [Unsupported policy details hallucinated](#11-agent-hallucinates-policy-details-wrong-numbers-fees-urls)
12. [False barge-in during long TTS responses](#12-false-barge-in-during-long-tts-responses)
13. [Second session silent after welcome message](#13-second-session-produces-no-response-after-welcome-message)
14. [First words dropped after greeting and late false barge-in](#14-first-words-dropped-after-greeting--late-echo-triggers-false-barge-in)
15. [High end-to-end latency](#15-high-end-to-end-latency--user-waits-56-seconds-for-response)
16. [Listening starts late after greeting — investigation open](#16-listening-starts-late-after-greeting-investigation-open)
17. [TTS stops unexpectedly during conversation — investigation open](#17-tts-stops-unexpectedly-during-conversation-investigation-open)
18. [Maximum VAD utterance duration prematurely ends a long user turn](#18-maximum-vad-utterance-duration-prematurely-ends-a-long-user-turn)
19. [VAD triggers STT endpoints while TTS has muted the provider](#19-vad-triggers-stt-endpoints-while-tts-has-muted-the-provider)
20. [TTS playback interruption after barge-in — investigation open](#20-tts-playback-interruption-after-barge-in-investigation-open)

---

## 1. Greeting Interruption (False Barge-In)

### Symptom

Greeting message starts playing but is interrupted after 1-2 seconds by a BARGE-IN event, cancelling the TTS.
```
[TTS] Starting stream for response_id=0: Hi, thanks for calling...

[AssemblyAI] Connected

[BARGE-IN] TTS cancelled, stop_audio sent to frontend
```

### Root Cause

Voice Activity Detection (VAD) in the frontend detects the greeting audio being played through speakers and microphone simultaneously. The microphone starts listening while greeting TTS is still playing, causing VAD to interpret speaker audio as user input.

### Solution

**File:** `examples/html/chatbot.html`

1. Add a flag to track greeting audio playback:
```javascript
let greetingAudioPlaying = false;
```

2. Set flag when greeting starts playing:
```javascript
if(msg.type==="greeting_done"){

    greetingAudioPlaying = true;

    playBufferedAudio();

}
```

3. Defer microphone startup until greeting finishes:
```javascript
if(msg.type==="listening_ready"){

    if(greetingAudioPlaying || (currentAudio && !currentAudio.paused)){

        pendingStartMic=true;  // Defer startup

    } else {

        await startMic();

    }

}
```

4. Clear flag when audio completes:
```javascript
audio.onended=async()=>{

    greetingAudioPlaying=false;

    if(pendingStartMic){

        pendingStartMic=false;

        await startMic();

    }

}
```

### Why This Works

- Microphone doesn't start until greeting audio completely finishes

- VAD doesn't run during greeting playback

- No speaker audio picked up as false user input

### Testing

Run `python main_rag.py` and click Start — greeting should play completely without interruption.

---

## 2. High RAG Lookup Latency

### Symptom

10+ seconds between user speaking and system response starting.
```
20:05:34: User says "How do I setup washing machine?"

20:05:44: TTS starts (10 second delay!)
```

### Root Causes

1. **Output limit too restrictive** — the response may be truncated or require follow-up generation; changing `max_tokens` does not inherently make token generation faster.
2. **Retrieval configuration** — `top_k` and the amount of context can affect retrieval and downstream LLM latency.
3. **Metadata filtering absent or ineffective** — filtering may reduce the candidate set when metadata and filter logic are correct.
4. **Multiple hold phrases** — extra spoken messages add audible time and may make the interaction feel slower.

Treat these as candidate contributors; profile each stage before attributing a latency improvement to one change.

### Solution

**File:** `sample_providers/rag/rag_provider.py`

1. Increase max_tokens:
```python
max_tokens: int = 400  # Was 150
```

2. Reduce top_k:
```python
top_k: int = 3  # Was 4
```

3. Add metadata filtering (category + topic):
```python
def _classify_query_category(self, query: str) -> str | None:

    """Classify into 'smartphones_tablets' or 'home_appliances'"""

    query_lower = query.lower()

    if any(kw in query_lower for kw in ["phone", "tablet", "screen"]):

        return "smartphones_tablets"

    if any(kw in query_lower for kw in ["refrigerator", "oven", "washer"]):

        return "home_appliances"

    return None

def _classify_query_topic(self, query: str) -> str | None:

    """Classify into topic: setup, troubleshooting, warranty, shipping"""

    query_lower = query.lower()

    if any(kw in query_lower for kw in ["setup", "install", "first time"]):

        return "setup_installation"

    if any(kw in query_lower for kw in ["error", "broken", "not working"]):

        return "troubleshooting"

    # ... more topics
```

4. Use filters in retrieval:
```python
where_filter = {

    "$and": [

        {"category": {"$eq": category}},

        {"topic": {"$eq": topic}},

    ]

}

results = vector_store.similarity_search_with_score(

    query=query,

    k=top_k,

    filter=where_filter,  # ← Key change

)
```

### Impact

- **Metadata filtering:** can reduce retrieval time; measure the actual improvement on the current index

- **Increased max_tokens:** Allows complete responses without truncation

- **Lower top_k:** Fewer documents to process

### Testing
```bash
python sample_providers/rag/test_rag_retrieval.py
```

Record retrieval latency over multiple runs and compare filtered vs. unfiltered queries. Treat <2 seconds as a project target, not a guaranteed result.

---

## 3. Small Talk Not Detected

### Symptom

User says "How are you?" but system triggers RAG search instead of going straight to LLM.
```
[RAG] Vector DB returned no results for query...

[RAG] Trying web search...
```

### Root Cause

Small talk detection was checking if **entire message** is in keyword set:
```python
return user_text.strip().lower() in SMALL_TALK_KEYWORDS  # ❌ Wrong!
```

This fails because:

- User says: "Hello, Maya. How are you?"

- Keyword set has: "hello", "how are you" (individual keywords)

- Entire normalized text ("hello, maya. how are you?") is NOT in set

### Solution

**File:** `sample_providers/rag/rag_provider.py`

Change to check if **any keyword is contained in** message:
```python
def _is_small_talk(self, user_text: str) -> bool:

    """Check if user message contains any small talk keyword."""

    text_lower = user_text.strip().lower()

    return any(keyword in text_lower for keyword in SMALL_TALK_KEYWORDS)
```

Also expand keywords to include meta-questions:
```python
SMALL_TALK_KEYWORDS = {

    "hello", "hi", "hey", "howdy",

    "how are you", "how's it going",

    "thank you", "thanks", "bye", "goodbye",

    "who are you", "what is your name",  # ← Meta-questions

    "tell me about yourself",

}
```

### Why This Works

- "Hello, Maya. How are you?" contains "hello" → Detected ✅

- "Who are you?" contains "who are you" → Detected ✅

- Goes straight to LLM without RAG

---

## 4. Small Talk Queries Slow

### Symptom

Small talk questions like "How are you?" take 5-10 seconds even though they should be instant.

### Root Cause

Code was running RAG retrieval in parallel with small talk check, then **waiting for both to complete**:
```python
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:

    small_talk_future = executor.submit(self._is_small_talk, user_text)

    retrieval_future = executor.submit(self._retrieve_docs, user_text)

    is_small = small_talk_future.result()

    rag_context, best_score, retrieval_elapsed = retrieval_future.result()  # ← Waits!
```

Even though small talk is detected early, the code waits for RAG to finish (5-10 seconds).

### Solution

**File:** `sample_providers/rag/rag_provider.py`

Check small talk FIRST and early-return without running RAG:
```python
def stream_chat(self, messages: list) -> Iterator:

    user_text = next(

        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""

    )

    # Check small talk FIRST (instant)

    if self._is_small_talk(user_text):

        logger.debug(f"[RAG] Small talk detected — bypassing RAG")

        yield from self.llm.chat.completions.create(

            model=self.model,

            messages=messages,

            stream=True,

            max_tokens=self.max_tokens,

        )

        return  # ← Exit immediately, don't run RAG

    # Only run RAG for product questions

    rag_context, best_score, retrieval_elapsed = self._retrieve_docs(user_text)

    # ... rest of logic
```

### Impact

- Small-talk queries should avoid unnecessary retrieval; measure end-to-end latency in the current environment.

- No unnecessary RAG retrieval

- No Tavily fallback

---

## 5. Incomplete RAG Responses

### Symptom

Setup instructions are incomplete. User asks for step-by-step but gets only 4 out of 10+ steps.

**Example:**
```
Q: "How do I set up my washing machine?"

A: "Download the app, connect to Wi-Fi, and you're ready."

   ❌ Missing: water inlet, drain hose, transit bolts, grounding, test cycle
```

### Root Cause

System prompt limits all responses to 2-3 sentences for voice:
```python
"so keep every answer to two or three sentences at most."
```

This is too restrictive for setup/installation queries which need 7-10 steps.

### Solution

**File:** `main_rag.py`

Update system prompt with query-type-specific length guidance:
```python
"RESPONSE LENGTH:\n"

"- For SETUP/INSTALLATION questions: Provide a complete summary covering all key steps. "

"Speak naturally as a flowing list (e.g., 'First do X, then do Y, then do Z'). "

"ALWAYS include any safety warnings or critical steps. Can be 4-6 sentences.\n"

"- For OTHER questions: Keep to 2-3 sentences.\n"
```

### Why This Works

- Setup queries get 4-6 sentences for completeness

- Other queries stay brief for voice

- Critical info is never truncated

### Testing

Ask: "How do I set up my washing machine?"

Response should include all steps including transit bolts warning.

---

## 6. Missing Critical Safety Information

### Symptom

Response omits critical safety warnings marked IMPORTANT in documentation.

**Example:**
```
PDF says: "IMPORTANT: Remove transit bolts from back before first use"

LLM response: ❌ Never mentions transit bolts

Result: Customer damages machine
```

### Root Cause

LLM has context but doesn't emphasize safety info. May be using pre-training knowledge instead of provided context.

### Solution

**File:** `main_rag.py`

Strengthen system prompt to forbid omitting safety info:
```python
"ALWAYS include ANY safety warnings, critical steps, or items marked IMPORTANT "

"in the documentation. NEVER omit safety information."
```

**File:** `sample_providers/rag/rag_provider.py`

Add runtime check to remind LLM about safety:
```python
# Check if context contains safety keywords

safety_keywords = ["transit bolt", "important:", "warning", "critical", "must", "danger"]

context_has_safety = any(

    keyword.lower() in (rag_context + web_context).lower()

    for keyword in safety_keywords

)

# If safety info exists, remind LLM to include it

if context_has_safety and augmented_messages:

    augmented_messages[-1]["content"] += (

        "\n\n⚠️ [SYSTEM REMINDER] Include any IMPORTANT, WARNING, or CRITICAL "

        "safety information from the knowledge base provided above."

    )
```

### Why This Works

- Two-layer protection: system prompt + runtime check

- LLM is explicitly reminded about safety info

- Prevents critical information from being dropped

---

## 7. Unreliable Web Search Results

### Symptom

Tavily returns false/hallucinated information.

**Example:**
```
Q: "Is Acme Electronics Fortune 500?"

Web search: "Yes, Acme Electronics is on the Fortune 500 list"

Result: ❌ Acme Electronics is fictional!
```

### Root Cause

No validation of Tavily results. Web search returns any matching result without verifying relevance or truthfulness.

### Solution

**File:** `sample_providers/rag/rag_provider.py`

Add guardrails to filter unreliable results:
```python
def _web_search(self, query: str) -> str:

    """Web search with guardrails."""

    if not self.tavily:

        return ""

    results = self.tavily.search(query=query, max_results=3)

    snippets = []

    query_terms = set(query.lower().split())

    for result in results.get("results", []):

        content = result.get("content", "").strip()

        if not content:

            continue

        # GUARDRAIL 1: Relevance - must contain 30%+ of query terms

        content_lower = content.lower()

        matching_terms = sum(1 for term in query_terms if term in content_lower)

        relevance_ratio = matching_terms / len(query_terms) if query_terms else 0

        if relevance_ratio < 0.3:

            logger.debug(f"Filtered: low relevance ({relevance_ratio:.1%})")

            continue

        # GUARDRAIL 2: Length - must be substantial (≥50 chars)

        if len(content) < 50:

            logger.debug(f"Filtered: too short ({len(content)} chars)")

            continue

        # GUARDRAIL 3: Sanity - avoid generic placeholders

        generic = ["click here", "read more", "for more", "learn more"]

        if any(phrase in content_lower for phrase in generic):

            logger.debug("Filtered: generic content")

            continue

        snippets.append(content)

    return "\n\n".join(snippets)
```

### Guardrails Explained

| Guardrail | Purpose | Example |

|-----------|---------|---------|

| **Relevance (30% match)** | Results must relate to query | "Fortune 500" query requires "Fortune" OR "500" mentioned |

| **Length (≥50 chars)** | Avoid placeholder results | Filters out "Click here for more..." |

| **Sanity check** | Avoid generic content | Filters "Learn more about..." |

### Result

If all results are filtered out, system returns "not found" instead of false information.

---

## 8. End-of-Speech Detection Slow

### Symptom

System takes too long to detect when user finishes speaking, causing delays before LLM processes input.

### Root Cause

AssemblyAI default settings are conservative (prevent false positives but slower detection).

### Solution

**File:** `voicestax/providers/stt/assemblyai.py`

Adjust AssemblyAI streaming parameters:
```python
url = (

    f"wss\://streaming.assemblyai.com/v3/ws"

    f"?sample_rate={self.sample_rate}"

    f"&encoding={self.encoding}"

    f"&format_turns=true"

    f"&end_of_turn_confidence_threshold=0.6"    # ← Was 0.5, more balanced

    f"&min_end_of_turn_silence_when_confident=300"  # ← Was 400ms, faster

)
```

### Parameter Explanation

- **end_of_turn_confidence_threshold=0.6**

  - 0.5 = very fast, may have false positives

  - 0.6 = balanced (recommended)

  - 0.7+ = very accurate but slow

- **min_end_of_turn_silence_when_confident=300**

  - 300ms = faster detection

  - 400ms = more stable

  - 700ms = most conservative

### Trade-off

- Lower values = faster but more false positives

- Higher values = accurate but slow

- **0.6 and 300ms = good balance for voice**

---

## 9. Logger Import Missing

### Symptom
```
[ERROR] name 'logger' is not defined
```

### Root Cause

Added logging statements to code without importing the logger utility.

### Solution

**File:** `sample_providers/rag/rag_provider.py`

Add import at top of file:
```python
from voicestax.utils.logger import logger
```

### Prevention

Always check imports before adding logging statements:
```python
from voicestax.utils.logger import logger  # ✅ Add this first

# ...

logger.info("Message here")  # Now this works
```

---

## 10. Agent Response Omits Policy Details (Timeframes, Steps, Warnings)

### Symptom

Agent gives a generic or incomplete answer even though the retrieved context contains specific, critical details.

**Example:**
```
Context says: "contact Acme support within 48 hours of delivery with photos and your order number"

Agent says:   "contact customer support within a few days"

              ❌ Wrong deadline, missing photo requirement
```

Additional omissions observed for a damaged delivery query:

- "Do not use the device" — omitted

- "48 hours" → paraphrased as "a few days" — factually wrong

- Photo requirement — omitted

- "Acme will arrange a replacement or full refund at no cost" — omitted

- "Do not return without contacting support — unauthorised returns may not be processed" — omitted

### Root Causes

**1. Response length rule too restrictive (`main_rag.py`)**

The system prompt had:
```python
"- For OTHER questions: Keep to 2-3 sentences."
```

Warranty/damage/returns queries fall into "OTHER" — a 2-3 sentence cap forces the model to drop most of the policy content.

**2. No instruction to preserve exact specifics (`main_rag.py`)**

The prompt said "Answer only from provided knowledge" but did NOT say "preserve exact numbers and deadlines." The model paraphrased "48 hours" → "a few days" without warning.

**3. Safety keyword list missed the pattern (`rag_provider.py`)**

The runtime safety check uses keywords to detect when context has critical info. The damaged delivery policy uses `"Note:"` and `"do not"` — neither was in the keyword list, so the safety reminder injected into the user message never fired.
```python
# Before — misses "Note:", "do not", specific timeframes

safety_keywords = ["transit bolt", "important:", "warning", "critical", "must", "danger"]
```

### Solution

**File:** `main_rag.py`

1. Add a new length category for warranty/returns/damage queries:
```python
"- For WARRANTY/RETURNS/DAMAGE questions: Cover ALL steps and requirements from the context. "

"Include exact deadlines, required items (e.g. photos, order number), and any warnings or notes. "

"NEVER paraphrase or approximate specific timeframes — if the context says '48 hours', say '48 hours'. "

"Can be 4-6 sentences.\n"
```

2. Add an explicit ACCURACY RULES section:
```python
"ACCURACY RULES:\n"

"NEVER paraphrase or approximate specific deadlines, timeframes, or requirements from the context. "

"If the context says '48 hours', say '48 hours'. If the context says 'photos required', say 'photos required'. "

"When the context contains a list of steps or requirements, cover ALL of them — do not skip any."
```

**File:** `sample_providers/rag/rag_provider.py`

Expand safety keywords to cover patterns used in policy docs:
```python
safety_keywords = [

    "transit bolt", "important:", "note:", "warning", "critical",

    "must", "danger", "do not", "unauthorized", "within 48", "within 7"

]
```

### Why This Works

- Damage/returns queries now get 4-6 sentences — enough to cover all policy steps

- Model is explicitly told not to paraphrase timeframes or numbers

- "Note:" and "do not" patterns in policy docs now trigger the safety reminder

- All three layers (length rule, accuracy rule, runtime safety check) work together

### Testing

Ask: "My smartphone was delivered damaged."

Expected response must include:

- Contact within **48 hours** (not "a few days")

- Bring **photos** and order number

- **Do not use** the device

- Acme will provide a **replacement or full refund at no cost**

- **Do not return** without contacting support first

---

| Issue | Root Cause | Quick Fix | Files |

|-------|-----------|-----------|-------|

| Greeting interrupted | VAD during TTS | Defer mic startup | `chatbot.html` |

| High latency | No metadata filtering | Add query classification | `rag_provider.py` |

| Small talk slow | Waits for RAG | Early-return on small talk | `rag_provider.py` |

| Small talk not detected | Wrong detection logic | Check keyword contained in text | `rag_provider.py` |

| Incomplete responses | Length limit too strict | Allow 4-6 sentences for setup | `main_rag.py` |

| Missing safety info | LLM drops context | Add safety reminder to prompt | `main_rag.py` `rag_provider.py` |

| False web results | No validation | Add Tavily guardrails | `rag_provider.py` |

| Slow STT detection | Conservative threshold | Adjust AssemblyAI params | `assemblyai.py` |

| Logger error | Missing import | Import logger | `rag_provider.py` |

| Policy details omitted | 2-3 sentence cap + no accuracy rules | Add returns category + accuracy rules | `main_rag.py` `rag_provider.py` |

| Hallucinated policy details | Wrong doc retrieved + no anti-hallucination rule | Fix classifier order + add anti-hallucination rule | `rag_provider.py` `main_rag.py` |

| False barge-in during TTS | VAD too sensitive + no echo calibration window | Raise threshold + add immunity window | `chatbot.html` |

| Second session silent after greeting | `task.cancel()` races with cancel event; `terminate_session` never sent; STT timeout too short | Remove `task.cancel()` from `stop_streaming`; raise timeout to 15 s | `assemblyai.py` `websocket_routes.py` |

| First words dropped after greeting + late false barge-in | `getUserMedia` latency eats first 300–500ms of speech; single echo frame above VAD threshold fires interrupt after immunity window | Pre-warm mic during greeting with `micSendEnabled=false`; require `VAD_SUSTAINED_FRAMES=4` consecutive frames | `chatbot.html` |

| 5–6 s response latency despite small-talk query | `mp3` format buffers all chunks client-side until `complete`; full TTS generation time added to perceived latency | Switch to `pcm_24000` + `optimize_latency=4`; convert int16→float32 server-side; play each chunk immediately via Web Audio API | `settings.py` `audio_manager.py` `chatbot.html` |

---

## 11. Agent Hallucinates Policy Details (Wrong Numbers, Fees, URLs)

### Symptom

Agent gives a confident, detailed answer that sounds correct but contains specific numbers, fees, URLs, and procedures that **are not in the knowledge base** — fabricated from pre-training knowledge about generic e-commerce returns.

**Example:**
```
Q: "My smartphone was delivered damaged. What can I do? How do I return it?"

Agent said:

  - "return within 30 days"               ❌ Policy says 48 HOURS, not 30 days

  - "restocking fee up to 15%"            ❌ Policy says "at no cost to you" — directly contradicted

  - "visit acme-electronics.com/returns"  ❌ No URL in policy — fabricated

  - "prepaid label via email in 24 hours" ❌ Not in policy — fabricated

  - "refund in 5-7 business days"         ❌ Not in policy — fabricated

  - "gift returns = store credit only"    ❌ Not in policy — fabricated

Agent omitted:

  - "contact within 48 hours"                          ❌ Most critical deadline — missing

  - "do not use the device"                            ❌ Missing

  - "photos + order number required"                   ❌ Missing

  - "do not return without contacting support first"   ❌ Missing
```

### Root Causes

**1. Topic classifier routes damaged-delivery queries to the wrong document**

**File:** `sample_providers/rag/rag_provider.py`

The query "damaged smartphone...how do I return it?" contains both `"return"` (matches `warranty_returns`) and `"delivered"` (matches `shipping_delivery`). The classifier checks `warranty_returns` **first**, so it wins. Pinecone retrieves a general returns policy document instead of the damaged-delivery policy.
```python
# Before — wrong order, "return" keyword fires before "delivered" is checked

if any(kw in query_lower for kw in ["warranty", "return", "refund", ...]):

    return "warranty_returns"   # ← wins for "how do I return it?"

if any(kw in query_lower for kw in ["shipping", "delivery", ...]):

    return "shipping_delivery"  # ← never reached
```

With the wrong document retrieved, the model has no correct context and fills the gaps with generic e-commerce return policy knowledge from pre-training.

**2. No anti-hallucination rule in system prompt**

**File:** `main_rag.py`

The prompt says "Answer only from provided knowledge" but the model confidently invents specific figures (15%, 30 days, 24 hours, 5-7 business days) not present in the context. There was no explicit rule forbidding this.

### Solution

**File:** `sample_providers/rag/rag_provider.py`

Add a combined damage+delivery check **before** the `warranty_returns` check:
```python
# Check damaged-delivery FIRST — before warranty_returns

# A "damaged item I received" query contains "return" but the relevant

# document is the damaged-delivery policy, not the general returns policy.

if any(kw in query_lower for kw in ["damaged", "damage"]) and any(

    kw in query_lower for kw in ["delivery", "delivered", "arrived", "received", "shipped"]

):

    return "shipping_delivery"

# Only reaches here if not a damaged-delivery case

if any(kw in query_lower for kw in ["warranty", "return", "refund", ...]):

    return "warranty_returns"
```

**File:** `main_rag.py`

Add an explicit anti-hallucination rule to the KNOWLEDGE section:
```python
"CRITICAL: Do NOT state any specific numbers, percentages, URLs, timeframes, fees, "

"or procedures that are not explicitly present in the provided context. "

"If the context does not mention a restocking fee, do not mention one. "

"If the context does not give a URL, do not give one. "

"If the context does not give a timeframe for refunds, do not give one."
```

### Why This Works

- Damaged + delivery keyword combination now correctly retrieves the damaged-delivery policy document, not the general returns policy

- The anti-hallucination rule explicitly prevents the model from adding specifics (fees, URLs, days) not in the context

- Works together with the ACCURACY RULES added in Issue #10

### Testing

Ask: "My smartphone was delivered damaged. How do I return it?"

Response MUST include:

- "48 hours" (not "30 days" or "a few days")

- Do not use the device

- Photos and order number required

- Contact support before returning

Response MUST NOT include:

- Any restocking fee percentage

- Any URL not in the context

- Any refund processing timeline not in the context

- Any policy detail that contradicts "at no cost to you"

---

## Testing Checklist

- [ ] Greeting plays without interruption

- [ ] Small talk queries respond in <1 second

- [ ] "How are you?" goes to LLM only (no RAG)

- [ ] Setup queries include all steps + safety warnings

- [ ] "Is Acme Fortune 500?" returns "not found" (not false info)

- [ ] Normal product queries work correctly

- [ ] No logger errors in console

- [ ] Response times are reasonable (<3 seconds)

---

## Performance Targets

| Query Type | Target Time | Threshold |

|-----------|------------|-----------|

| Small talk | <1 second | Voice-only, no RAG |

| Product question | 2-3 seconds | RAG + LLM |

| Setup guide | 3-5 seconds | RAG + longer response |

| Not found | <2 seconds | No Tavily if guardrails filter |

---

## Future Improvements

1. **Caching** - Cache common queries to reduce latency

2. **Hybrid search** - Add BM25 keyword search for technical terms

3. **Better chunk strategy** - Extract critical info as metadata

4. **A/B testing** - Test confidence thresholds on real users

5. **Monitoring** - Log and track response quality metrics

---

## 12. False Barge-In During Long TTS Responses

### Symptom

Barge-in fires and cuts off TTS mid-sentence even though the user said nothing. Happens especially on longer responses (15+ seconds of audio).
```
[2026-03-31 12:07:38] [TTS] Starting stream: If your smartphone arrived damaged...

[2026-03-31 12:08:11] [BARGE-IN] TTS cancelled, stop_audio sent to frontend

← 33 seconds later, user never spoke
```

### Root Causes

**1. VAD threshold too low (`chatbot.html`)**

`VAD_THRESHOLD = 0.015` is very sensitive. Background noise (fan, HVAC, distant sounds) or faint speaker echo can exceed this level, triggering a false interrupt. The browser's `echoCancellation: true` helps but takes time to adapt — longer responses give more chances for bleed-through.

**2. No immunity window at TTS start (`chatbot.html`)**

VAD fires immediately when `isAiSpeaking = true`. Browser echo cancellation needs ~1 second to calibrate to the new audio being played. During this calibration period, speaker audio leaks through and appears as microphone input above the threshold.

### Solution

**File:** `examples/html/chatbot.html`

1. Raise VAD threshold to reduce sensitivity to background noise:
```javascript
const VAD_THRESHOLD = 0.025;  // was 0.015
```

2. Add a TTS start immunity window — ignore VAD for the first 1.5s after TTS begins:
```javascript
const TTS_START_IMMUNITY_MS = 1500;

let   ttsStartedAt          = 0;
```

3. Record when TTS starts:
```javascript
if(msg.type==="audio_chunk"){

  if(!isAiSpeaking) ttsStartedAt = Date.now();  // record start for immunity window

  isAiSpeaking = true;

  ...

}
```

4. Gate the VAD interrupt on both cooldown AND immunity window:
```javascript
if(isAiSpeaking && rms > VAD_THRESHOLD){

  const now    = Date.now();

  const ttsAge = now - ttsStartedAt;

  if(!interruptSent && now - lastInterruptAt > VAD_COOLDOWN_MS && ttsAge > TTS_START_IMMUNITY_MS){

    interruptSent = true;

    sendInterrupt();

  }

}
```

### Why This Works

- Raising threshold (0.015 → 0.025) filters out background noise that doesn't represent real speech

- The 1.5s immunity window lets echo cancellation calibrate before VAD can fire

- Legitimate barge-ins (user actually speaking) produce RMS well above 0.025 and occur after the immunity period

### Trade-offs

| Setting | Too low / short | Too high / long |

|---|---|---|

| `VAD_THRESHOLD` | False positives from background noise | Misses soft-spoken barge-ins |

| `TTS_START_IMMUNITY_MS` | Echo still triggers at start | Delays response to early real barge-in |

| Recommended | 0.025, 1500ms | Adjust up if still false-triggering |

### Testing

Start the session and let a long response (10+ sentences) play fully without speaking.

No `[BARGE-IN]` log line should appear in the server console.

---

---

## 13. Second Session Produces No Response After Welcome Message

### Symptom

After completing a conversation and clicking **Start** again, the welcome message plays correctly but then the assistant gives no response to anything the user says.
```
[15:39:22] [INFO] voicestax: [Router] Session end detected — cleaning up

[15:39:23] [INFO] voicestax: [AssemblyAI] WebSocket closed

[15:39:36] [INFO] voicestax: [TTS] Starting stream for response_id=0: Hi! Welcome to VoiceStax...

[15:39:42] [INFO] voicestax: [AssemblyAI] Connecting: wss\://streaming.assemblyai.com/...

[15:39:48] [ERROR] voicestax: ❌ STT never became ready

[15:39:48] [INFO] voicestax: [AssemblyAI] Connected

[15:39:48] [INFO] voicestax: [AssemblyAI] Session began: 3605beac-...

← No transcripts logged after this. Assistant silent.
```

Note the absence of `[AssemblyAI] Cancelled` in the first session's shutdown — this is the key indicator of the bug.

### Root Cause

Two compounding issues:

**1. `stop_streaming()` calls `_stream_task.cancel()` which races with `_cancel_event.set()`**

In Python 3.9+, `asyncio.CancelledError` is a `BaseException` (not `Exception`). When `_stream_task.cancel()` is called at the same time as `_cancel_event.set()`, `CancelledError` is injected into `_run_stream` at the `await asyncio.wait(...)` line — *before* the graceful shutdown branch can execute. The graceful path (`if cancel_task in done:`) never runs, so the `{"terminate_session": True}` message is **never sent** to AssemblyAI.

AssemblyAI keeps the old session alive for ~6 seconds until it self-times-out. The next connection attempt is therefore much slower than usual.

**2. The STT ready timeout (5 seconds) is shorter than the delayed reconnection (~6 seconds)**
```python
# websocket_routes.py — before fix

if wait_attempts > 100:   # 100 × 50ms = 5 seconds

    logger.error("❌ STT never became ready")

    break
```

After the `break`, `stt_accepting = True` is set and `listening_ready` is sent to the client anyway. The client starts the microphone immediately. But AssemblyAI hasn't connected yet — `is_streaming = False` — so every audio frame from the mic is silently dropped by `send_audio`:
```python
if not self.is_streaming or not self._ws or not self._is_listening:

    return   # ← audio dropped here
```

By the time AssemblyAI connects (~1 second later), the user may have started speaking into what they believe is an active session, but those first words were discarded.

### Solution

**File:** `voicestax/providers/stt/assemblyai.py`

Remove `_stream_task.cancel()` from `stop_streaming`. The `_cancel_event` alone is sufficient for graceful shutdown — it completes `cancel_task` inside `asyncio.wait`, the code sends `terminate_session`, and the WebSocket closes cleanly.
```python
def stop_streaming(self):

    self._is_listening = False

    self.is_streaming = False

    self._cancel_event.set()

    # Do NOT call self._stream_task.cancel() here.

    # In Python 3.9+, CancelledError (BaseException) races with the cancel

    # event and prevents terminate_session from being sent, causing the next

    # connection to stall for ~6 seconds.
```

**File:** `voicestax/api/websocket_routes.py`

Increase the safety timeout from 5 s to 15 s:
```python
if wait_attempts > 300:   # 300 × 50ms = 15 seconds

    logger.error("❌ STT never became ready")

    break
```

### Why This Works

- `_cancel_event.set()` fires `cancel_task` in `asyncio.wait`, entering the graceful shutdown branch

- `terminate_session` is sent → AssemblyAI immediately frees the session

- Next `start_streaming` connects in normal time (~1–2 s)

- The 15-second safety timeout is a backstop for genuine network delays

### How to Identify This Bug in Logs

| Log line | Meaning |

|---|---|

| `[AssemblyAI] WebSocket closed` **without** preceding `[AssemblyAI] Cancelled` | `terminate_session` was NOT sent — task was force-cancelled |

| `❌ STT never became ready` on second+ session | AssemblyAI is slow to connect because old session wasn't terminated |

| No transcript logs after `Session began` | Audio was dropped during the connection gap |

### Files Changed

- `voicestax/providers/stt/assemblyai.py` — removed `_stream_task.cancel()`

- `voicestax/api/websocket_routes.py` — increased ready timeout to 300 attempts (15 s)

---

---

## 14. First Words Dropped After Greeting + Late Echo Triggers False Barge-In

Two symptoms observed together in the same session.

---

### Symptom A — First words of user speech dropped after greeting

User says "Hello Maya, how are you?" but only "how are you?" is transcribed. The opening words are silently lost every time after the assistant's greeting plays.
```
[20:18:37] [AssemblyAI] Session began: b2ecd924-...

[20:18:41] [AssemblyAI] Turn (formatted final): How are you?

← "Hello Maya" was never logged
```

#### Root Cause

After the greeting audio finishes playing on the client, the `listening_ready` message has already arrived. The `audio.onended` handler calls `startMic()`, which calls the browser's `getUserMedia()` API. `getUserMedia` takes **200–500 ms** to resolve (permission check, stream initialisation). The user hears silence when the greeting ends and immediately starts speaking — "Hello Maya" is spoken during that setup window before the microphone is actually streaming.

#### Solution

**File:** `examples/html/chatbot.html`

Pre-warm the microphone during the greeting (2–3 seconds of lead time) so `getUserMedia` completes long before the user can speak. Audio bytes are gated by a `micSendEnabled` flag and are not forwarded to the server until the greeting audio ends.

1. Add the send-gate flag:
```javascript
let micSendEnabled = false;
```

2. Gate `onaudioprocess` on the flag:
```javascript
processor.onaudioprocess = (e) => {

  if (ws.readyState !== WebSocket.OPEN || !micSendEnabled) return;

  ws.send(floatTo16BitPCM(e.inputBuffer.getChannelData(0)));

};
```

3. In `stopMic()`, reset the gate:
```javascript
function stopMic() {

  micSendEnabled = false;

  // ...existing teardown...

}
```

4. In the `greeting_started` handler, kick off mic initialisation early (but don't enable sending):
```javascript
if (msg.type === "greeting_started") {

  // ...existing code...

  startMic(false).catch(() => {});  // pre-warm: getUserMedia runs now

  return;

}
```

5. Modify `startMic` to accept a `sendEnabled` flag and skip `getUserMedia` if the stream is already live:
```javascript
async function startMic(sendEnabled = true) {

  if (micStream) {

    micSendEnabled = sendEnabled;

    if (!vadRafHandle) startVAD();

    return;

  }

  // ...existing getUserMedia + processor setup...

  micSendEnabled = sendEnabled;

  startVAD();

}
```

6. When greeting audio ends and `pendingStartMic` is set, `startMic()` now returns immediately (mic already live) and just flips the flag:
```javascript
if (pendingStartMic) {

  pendingStartMic = false;

  await startMic();   // no-op for getUserMedia — just sets micSendEnabled = true

  setBadge("Listening"); modeEl.textContent = "Listening";

}
```

#### Why This Works

- `getUserMedia` resolves during the greeting (2–3 seconds of slack time)

- `micSendEnabled = false` ensures no bytes are forwarded to the server while the greeting plays

- The instant the greeting audio ends, `startMic()` skips `getUserMedia`, sets `micSendEnabled = true`, and the first audio frame is sent with zero extra latency

---

### Symptom B — TTS response cut off mid-sentence by false barge-in ~13 seconds in

A long TTS answer is interrupted roughly 13 seconds after it starts, even though the user said nothing. The 1.5s immunity window (added in Issue #12) had already expired.
```
[20:19:04] [TTS] Starting stream for response_id=0: Let me pull that up...

[20:19:17] [BARGE-IN] TTS cancelled, stop_audio sent to frontend

[20:19:17] [AssemblyAI] Forced end of turn

← 13 seconds in, user never spoke
```

#### Root Cause

The frontend VAD evaluates RMS on **every animation frame** (~16ms at 60fps). The immunity window (`TTS_START_IMMUNITY_MS = 1500`) guards only the first 1.5s. For longer responses, room echo or speaker bleed occasionally produces a single frame that crosses `VAD_THRESHOLD`. One frame above threshold was enough to immediately send an interrupt.

#### Solution

**File:** `examples/html/chatbot.html`

Require a minimum number of **consecutive** frames above the threshold before sending an interrupt. A single echo spike resets the counter; sustained user speech (hundreds of ms) accumulates enough frames to trigger.
```javascript
const VAD_SUSTAINED_FRAMES  = 4;   // ~65ms at 60fps before interrupt fires

let   vadAboveThresholdFrames = 0;
```

Modify `vadTick`:
```javascript
if (isAiSpeaking && rms > VAD_THRESHOLD) {

  vadAboveThresholdFrames++;

  const now    = Date.now();

  const ttsAge = now - ttsStartedAt;

  if (!interruptSent && vadAboveThresholdFrames >= VAD_SUSTAINED_FRAMES &&

      now - lastInterruptAt > VAD_COOLDOWN_MS && ttsAge > TTS_START_IMMUNITY_MS) {

    interruptSent = true;

    lastInterruptAt = now;

    sendInterrupt();

  }

} else if (rms < VAD_THRESHOLD * 0.5) {

  vadAboveThresholdFrames = 0;   // reset on silence — spike protection

  interruptSent = false;

}
```

Also reset the counter when TTS starts and when audio is stopped:
```javascript
// In audio_chunk handler:

if (!isAiSpeaking) { ttsStartedAt = Date.now(); vadAboveThresholdFrames = 0; }

// In stopLocalAudio():

vadAboveThresholdFrames = 0;
```

#### Why This Works

- A transient echo spike (1–2 frames, ~16–33ms) no longer triggers an interrupt

- Real user speech is sustained for hundreds of ms, easily reaching the 4-frame threshold

- The 0.5× hysteresis band (`rms < VAD_THRESHOLD * 0.5`) resets the counter cleanly between spikes

#### Trade-offs

| `VAD_SUSTAINED_FRAMES` | Effect |

|---|---|

| 1 (original) | Triggers on any single spike — false positives on echo |

| 4 (recommended) | ~65ms sustained audio required — eliminates brief echo |

| 8+ | Very robust against echo, but adds noticeable delay to real barge-ins |

---

### Files Changed

- `examples/html/chatbot.html` — mic pre-warm logic, `micSendEnabled` flag, `VAD_SUSTAINED_FRAMES` counter

---

---

## 15. High End-to-End Latency — User Waits 5–6 Seconds for Response

### Symptom

User finishes speaking and waits 5–6 seconds before hearing any audio response, even for simple small-talk queries that bypass RAG.
```
08:32:06 PM — transcription "hello maya how are you" appears in chat

08:32:12 PM — AI response audio starts playing

← 6-second gap; LLM-only queries should be ~2s
```

### Root Cause

**Two compounding settings produced the worst-case buffered latency:**

**1. `tts_output_format = "mp3_22050_32"` (`settings.py`)**

mp3 chunks arriving at the client **cannot be played incrementally** in the browser — there is no native browser API to append mp3 data to an in-progress audio stream. The frontend stores every chunk in `audioBufferChunks` and only begins playback when the `complete` message arrives (i.e. after ElevenLabs has finished generating the *entire* response).
```
Turn detected

  → LLM inference:           ~1–2 s

  → ElevenLabs generates ALL audio:  ~1–3 s   ← user waits silently

  → `complete` received by client

  → mp3 blob assembled + play()

  → user hears first word

Total perceived latency: 3–6 s
```

**2. `tts_optimize_latency = 3` (`settings.py`)**

ElevenLabs supports optimization levels 0–4. Level 4 is the maximum streaming-specific setting. Level 3 leaves measurable latency on the table for streaming use cases.

### Solution

**File:** `voicestax/config/settings.py`

Switch to raw PCM output and maximum latency optimization:
```python
tts_output_format: str = "pcm_24000"  # was "mp3_22050_32"

tts_optimize_latency: int = 4          # was 3
```

**File:** `voicestax/core/audio_manager.py`

Detect PCM format and convert each int16 chunk to float32 before sending, so the client can play it immediately via Web Audio API:
```python
def _pcm_to_float32(self, pcm_bytes: bytes) -> bytes:

    """Convert int16 little-endian PCM (ElevenLabs pcm_24000) to float32 for Web Audio API."""

    n = len(pcm_bytes) // 2

    samples = struct.unpack_from(f'<{n}h', pcm_bytes)

    return struct.pack(f'{n}f', *(s / 32768.0 for s in samples))
```

In `stream_text`, detect format and set encoding per chunk:
```python
is_pcm = str(getattr(self.tts_client, 'output_format', '') or '').lower().startswith('pcm_')

# In the chunk loop:

send_bytes = self._pcm_to_float32(chunk) if is_pcm else chunk

await websocket.send_json({

    "type": "audio_chunk",

    "audio": base64.b64encode(send_bytes).decode(),

    "encoding": "pcm_f32" if is_pcm else "mp3",

    "response_id": response_id,

})
```

For PCM, send word messages **before** `complete` (so they are queued client-side before `finaliseStream()` runs). For mp3, keep the existing order (complete first, then words with timing delays):
```python
if is_pcm:

    for i, word in enumerate(words):   # no per-word sleep

        await websocket.send_json({"type": "word", ...})

    await websocket.send_json({"type": "complete", ...})

else:

    await websocket.send_json({"type": "complete", ...})

    for i, word in enumerate(words):

        await websocket.send_json({"type": "word", ...})

        await asyncio.sleep(delay_per_word_ms / 1000)
```

**File:** `examples/html/chatbot.html`

When `playBufferedAudio()` is called with an empty buffer (PCM path), the audio is already playing. Schedule `isAiSpeaking = false` to fire when the last Web Audio chunk finishes:
```javascript
function playBufferedAudio(){

  if(!audioBufferChunks.length){

    finaliseStream();  // reveals all queued words immediately

    const delayMs = playAudioContext

      ? Math.max(0, (nextTime - playAudioContext.currentTime) * 1000)

      : 0;

    setTimeout(()=>{

      isAiSpeaking=false; interruptSent=false; vadAboveThresholdFrames=0;

      // restore mic / session state as needed

    }, delayMs);

    return;

  }

  // ... existing mp3 path unchanged ...

}
```

In the `complete` handler, only flip the badge to "Listening" for the mp3 path — for PCM the badge is updated inside the setTimeout above:
```javascript
if(msg.type==="complete"){

  const wasPcm = audioBufferChunks.length===0;

  finaliseStream(); playBufferedAudio();

  if(!wasPcm){ setBadge("Listening"); modeEl.textContent="Listening"; }

  return;

}
```

### Why This Works

| Format | Client receives first chunk | User hears first word |

|---|---|---|

| mp3 | Buffered — plays after `complete` | LLM + **full** TTS generation |

| pcm_24000 | Plays immediately via Web Audio API | LLM + **first** TTS chunk TTFB |

ElevenLabs `pcm_24000` output is 16-bit signed little-endian PCM at 24 kHz — exactly matching the `playAudioContext` sample rate. The existing `playStreamChunk` function already handles `encoding: "pcm_f32"` chunks; no client-side playback code needed to change.

### Expected Latency After Fix

| Component | Before | After |

|---|---|---|

| LLM inference | ~1–2 s | ~1–2 s (unchanged) |

| ElevenLabs TTFB | hidden inside buffering | ~200–400 ms |

| Full TTS generation wait | ~1–3 s | eliminated |

| ****Total perceived**** | ****~3–6 s**** | ****~1.5–2.5 s**** |

### Format Reference (ElevenLabs)

| Format | Streamable in browser | Notes |

|---|---|---|

| `mp3_22050_32` | No — must buffer until complete | Low bitrate, small payload |

| `mp3_44100_128` | No — must buffer until complete | Higher quality |

| `pcm_24000` | Yes — via Web Audio API | Recommended for real-time voice |

| `pcm_44100` | Yes — via Web Audio API | Higher quality, larger payload |

### Testing

Start a session and say a simple greeting. The AI response audio should begin within ~2 seconds of the transcription appearing, even for multi-sentence responses.

### Files Changed

- `voicestax/config/settings.py` — `tts_output_format`, `tts_optimize_latency`

- `voicestax/core/audio_manager.py` — `_pcm_to_float32()`, PCM detection, word/complete ordering

- `examples/html/chatbot.html` — empty-buffer `playBufferedAudio`, `complete` badge logic

---

## 16. Listening Starts Late After Greeting — Investigation Open

**Status:** Open investigation. Do not treat this entry as a resolved bug.

### Symptom

After the assistant's greeting finishes, the user may start speaking before the UI changes to `Listening`. Speech spoken during this gap may not be transcribed. In recent manual testing, the user observed that transcription only began after the UI entered the listening state.

### What to instrument

Add timestamps for the same session/response ID at each boundary:

1. Server begins and finishes producing the greeting TTS stream.
2. Browser receives the final audio chunk / completion event.
3. Browser playback actually ends (`AudioBufferSourceNode.onended`, media `ended`, or the equivalent used by the current player).
4. Server marks STT as unmuted/accepting audio.
5. Frontend transitions to `Listening` and enables microphone forwarding.
6. First microphone frame is sent, accepted by the STT provider, and transcribed.

### Current hypotheses to test

- The server's TTS-completion state and actual browser playback completion are not aligned.
- Microphone initialisation or enabling audio forwarding happens only after playback ends, creating a setup gap.
- The frontend status update and the server's STT-acceptance state are racing or using different event semantics.

These are hypotheses, not confirmed root causes.

### Next diagnostic step

Reproduce by speaking immediately when the greeting ends. Compare the timestamps above and determine the first boundary that is delayed. Fix that boundary rather than adding arbitrary sleep values. Ensure any microphone pre-warming does not forward greeting echo to STT or permit false barge-in.

### Verification checklist

- [ ] Speech started immediately after the greeting is captured from its first words.
- [ ] No greeting audio is transcribed as user speech.
- [ ] Repeated sessions behave the same way.
- [ ] Normal barge-in still works during later TTS responses.

---

## 17. TTS Stops Unexpectedly During Conversation — Investigation Open

**Status:** Open investigation. No root cause has been confirmed from the information currently recorded.

### Symptom

During a conversation, assistant audio sometimes stops before the response is complete even though the user did not intentionally interrupt. The manual interrupt control itself was reported to work in recent testing.

### Logs to capture

For every response, log a stable `response_id` and timestamps for:

- TTS request start, first chunk, final chunk, normal iterator completion, and exceptions.
- Number of audio chunks and bytes generated and sent.
- Every cancellation request and its reason (user interrupt, new response, disconnect, timeout, or cleanup).
- Cancellation-event state and response-ID checks in the TTS worker/queue.
- Every `clear_audio` / stop-playback message sent to the browser, including its trigger.
- Browser audio scheduling, playback start, playback end, and playback errors.
- STT mute/unmute transitions and session shutdown/cleanup.

Do not log credentials or full sensitive user transcripts.

### Diagnostic interpretation

- **Provider stream ends early:** compare generated chunks and provider completion/error signals.
- **Server sends all chunks but browser stops:** investigate WebSocket ordering, `clear_audio`, audio queue scheduling, and browser playback state.
- **Cancellation occurs without user speech:** trace the caller and reason that set the cancellation event or changed the active response ID.
- **Old response cleanup affects a newer response:** make cleanup conditional on the response/session identity so stale tasks cannot change current playback or STT state.

These are diagnostic branches, not conclusions about the cause.

### Verification checklist

- [ ] A long response completes without user input or unexpected stop events.
- [ ] User barge-in cancels promptly and intentionally.
- [ ] Repeated interruptions do not leave stale audio queued.
- [ ] STT reliably returns to the expected state after normal completion and cancellation.
- [ ] Server-side chunk completion agrees with browser playback completion.

---

**Historical last-updated value in original file:** 2026-03-31

**Historical version value in original file:** 1.0.0

**Related Files:** `main_rag.py`, `sample_providers/rag/rag_provider.py`, `examples/html/chatbot.html`

---

**Last reviewed:** 2026-10-30 (VAD/STT/TTS debugging update)

---

---

## 18. Maximum VAD Utterance Duration Prematurely Ends a Long User Turn

**Status:** Root cause confirmed from the 2026-10-30 test logs. The proposed state-machine and router changes below are a design recommendation and must be verified in code/tests before being marked resolved.

### Symptom

A user speaks continuously for longer than the configured `max_utterance_ms`. VoiceStax starts responding even though the user has not finished the sentence. The remainder of the user's speech is then treated as a new turn.

### Confirmed evidence (2026-10-30)

At approximately 10:32:05, the VAD logged `max utterance reached`, followed by the router logging `Max utterance reached`, flushing a small remaining buffer, and sending `ForceEndpoint`. The formatted AssemblyAI turn immediately before this ended mid-sentence at:

```text
... or machine learning, what do
```

This shows that the configured maximum duration caused the router to force an STT turn boundary while the user was still speaking. It was not evidence that the user had finished their thought.

### Root cause

The current `VADManager.process_frame()` calls `self.reset()` when `speech_frames >= max_utterance_frames`, then emits `max_utterance`. The reset clears `in_speech`, so the manager forgets that the same continuous speech activity is still in progress.

The router currently handles both `speech_ended` and `max_utterance` in the same finalization block and sends `ForceEndpoint` for either event. This incorrectly treats a safety limit as proof of conversational turn completion.

### Recommended design

Treat the maximum as an **audio segment boundary**, not a **conversation turn boundary**:

1. On reaching the maximum, emit `max_utterance` (or rename it to `max_segment_reached` in a future API-breaking release).
2. Reset only the per-segment speech-frame counter and segment silence counter. Keep `in_speech = True` and do not clear the speech-candidate state as though speech had ended.
3. In the router, flush any pending audio bytes to the existing STT stream at this segment boundary. Do not send `ForceEndpoint` and do not start LLM processing.
4. Continue sending subsequent audio to the same active STT stream.
5. Only `speech_ended` after the configured continuous-silence threshold should trigger the final flush and `ForceEndpoint` for the conversational turn.

Illustrative state-machine change:

```python
if self.speech_frames >= self.max_utterance_frames:
    logger.warning("VAD: max segment duration reached")

    # End this local segment, but preserve the active speech state.
    self.speech_frames = 0
    self.silence_ms = 0
    events.append("max_utterance")
```

This is a focused illustration, not a complete router patch. The router must separately handle `max_utterance` (flush only) and `speech_ended` (flush + endpoint). Keep the maximum-duration guard: it prevents a continuously speech-classified signal from growing one unbounded VAD segment.

### Important implementation detail

The maximum event is raised while the current frame is speech. Keeping `in_speech=True` allows subsequent silence frames to accumulate toward the normal silence threshold. If the manager calls `reset()` at the maximum, the later silence is treated as pre-speech silence and the true end of that utterance can be missed.

### Verification tests

- [ ] With a short max duration in a unit test, continuous speech emits `max_utterance` at each segment limit without emitting `speech_ended`.
- [ ] After a max event, silence frames still accumulate; the configured silence threshold emits exactly one `speech_ended`.
- [ ] Router flushes audio on `max_utterance` but does not call `ForceEndpoint` or invoke the LLM.
- [ ] A long continuous utterance produces one completed transcript/LLM turn after the user pauses, not one response per maximum-length segment.
- [ ] A genuine pause shorter than the silence threshold does not end the turn; a pause at or beyond the threshold does.
- [ ] Session cleanup still resets all VAD state.

---

## 19. VAD Triggers STT Endpoints While TTS Has Muted the Provider

**Status:** Confirmed from the 2026-10-30 router and AssemblyAI logs. The unwanted endpoint calls are confirmed; their contribution to the separate TTS playback interruption is not proven.

### Symptom

While the assistant is speaking, the AssemblyAI provider is muted, but the router continues processing microphone frames. VAD can report `speech_ended` or `max_utterance`, and the router can still create a `ForceEndpoint` task.

### Confirmed evidence (2026-10-30)

During TTS playback:

- AssemblyAI logged that the provider was muted.
- The router later logged VAD speech end (`speech_frames=85`), flushed audio, and attempted to send it.
- AssemblyAI logged that it was ignoring audio because the provider was muted.
- Despite the mute, the router logged `Sending ForceEndpoint to STT` and created another endpoint task.

This proves that provider-level mute does not disable the router's VAD, audio buffering, or endpoint-task logic.

### Root cause

Muting is implemented at the STT provider's `send_audio()` boundary. The router has already buffered microphone frames and updated `endpoint_speech_frames` before it calls the provider. The endpoint handler is not gated by the assistant's speaking state. Therefore, audio can be discarded by the provider while the router still treats the associated VAD event as an STT turn boundary.

### Recommended behaviour

Do not disable microphone monitoring during TTS; that would break server-side barge-in detection. Instead, separate **barge-in monitoring** from **normal STT turn collection**:

- Keep VAD running while TTS plays so sustained user speech can be detected.
- Do not send ordinary microphone audio to the muted STT provider or trigger normal `speech_ended` / `max_utterance` endpoint handling during TTS.
- Retain a short rolling pre-roll buffer of microphone frames while TTS is playing.
- When barge-in is confirmed, cancel TTS, transition to listening, send the retained pre-roll frames to STT, and then stream subsequent frames normally.
- After the interrupted user's utterance reaches its actual silence boundary, flush and send one `ForceEndpoint`.
- Clear or reinitialize the pre-roll buffer at well-defined session/response transitions so old assistant echo or stale audio is not submitted as user speech.

A simple `session.state != "speaking"` condition around the existing endpoint block is not a complete solution: it prevents endpoints during TTS but can also lose the beginning of a real interruption unless pre-roll audio is preserved and replayed after barge-in confirmation.

### Verification tests

- [ ] While TTS is speaking and no user speaks, VAD may classify microphone frames, but no STT audio send or `ForceEndpoint` is attempted.
- [ ] Background fan noise does not create endpoint tasks during TTS.
- [ ] A real user interruption reaches the barge-in threshold and cancels TTS.
- [ ] The first words used to trigger barge-in are included in the audio sent to STT.
- [ ] After barge-in, the user can finish speaking and exactly one normal endpoint is produced.
- [ ] Normal listening after TTS completion still works.

---

## 20. TTS Playback Interruption After Barge-In — Investigation Open

**Status:** Open. Do not attribute the TTS playback break to VAD, ForceEndpoint, WebSocket throughput, or browser buffering until the complete cancellation/playback trace is captured.

### Symptom

In recent manual tests, several conversations played normally, but TTS sometimes broke or stopped after a manual or automatic interruption. In one reported sequence, a later TTS response stopped shortly after another interruption/transcription cycle.

### What the 2026-10-30 logs establish

- The first long user utterance was cut at the configured VAD maximum and prematurely finalized; see Issue #18.
- While TTS was playing, the router still processed VAD events and attempted a ForceEndpoint even though AssemblyAI was muted; see Issue #19.
- In the available log excerpt, ElevenLabs produced a first chunk after approximately 764 ms. WebSocket audio-chunk send durations were mostly in the low tens of milliseconds, with one observed send around 43 ms. These measurements do not show an obvious server WebSocket-send bottleneck in that excerpt.
- The supplied excerpt ended while TTS chunks were still being sent. It did not contain a corresponding `[BARGE-IN]` event, `_cancel_tts` trace, complete response termination, or browser playback-end/error event.

Therefore, the available excerpt cannot explain why the reported later TTS playback stopped. The fact that an endpoint was triggered while STT was muted is a confirmed defect, but it is not yet proven to be the direct cause of TTS audio stopping.

### Required diagnostics

Capture one complete affected response from before TTS starts until the browser either finishes playback or stops unexpectedly. Include:

- Stable session ID and TTS `response_id` on every log line.
- TTS provider iterator start, first chunk, each chunk sequence/byte count, final chunk, normal completion, and exception.
- Every `_cancel_tts()` invocation, caller/reason, cancellation-event state, and whether `clear_audio` / stop-audio was sent.
- Whether an old TTS worker or cleanup task can affect a newer response.
- Browser receipt of chunks, playback generation, queue/scheduled audio state, `clear_audio` handling, and actual audio-node `onended` / playback error events.
- STT mute/unmute and endpoint events, with timestamps, to correlate but not assume causation.

### Diagnostic rule

- If the server stops generating chunks, inspect provider iteration and cancellation.
- If the server sends all chunks but the browser stops, inspect frontend playback scheduling, generation IDs, queue clearing, and audio-node lifecycle.
- If `_cancel_tts()` fires unexpectedly, trace the exact caller and trigger before changing VAD thresholds.
- If no cancellation occurs but browser playback stops, do not label it a barge-in bug; investigate client playback separately.

### Verification checklist

- [ ] A long TTS response plays to completion without user input.
- [ ] One deliberate barge-in stops only the active response.
- [ ] The next response plays from its first chunk to completion.
- [ ] Repeated barge-ins do not let stale cancellation or cleanup affect a newer response.
- [ ] Server chunk counts and browser playback completion agree.

---

