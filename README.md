# Open WebUI Extensions

A collection of extensions for [Open WebUI](https://github.com/open-webui/open-webui) v0.9.0+, enhancing its functionality with automatic memory management, native Claude integration, web search, image generation, code analysis, and more.

## Compatibility

| Open WebUI Version | Status |
|---|---|
| >= 0.9.0 | Fully supported |
| < 0.9.0 | Not supported (async API changes) |

## Available Extensions

### Filters

| Extension | Description | Version |
|---|---|---|
| [Auto Memory](filters/auto_memory.py) | Automatically identifies, retrieves, and stores memories from conversations | 4.0.0 |
| [Rate Limiter](filters/rate_limiter.py) | Per-user rate limiting with minute/hour/sliding window controls | 0.3.0 |

### Actions

| Extension | Description | Version |
|---|---|---|
| [Extended Thinking](actions/extended_thinking.py) | Toggle extended thinking mode with configurable reasoning effort | 1.0.0 |

### Pipelines (Manifold Pipes)

| Extension | Description | Version |
|---|---|---|
| [Auto Claude](pipelines/auto_claude.py) | Native Anthropic Claude pipeline with thinking, vision, and tool use | 0.5.0 |

### Tools

| Extension | Description | Version |
|---|---|---|
| [Auto Code Analysis](tools/auto_code_analysis.py) | Execute Python code in sandboxed environments (Jupyter or E2B) | 1.1.0 |
| [Auto Image](tools/auto_image.py) | Native image generation and editing using built-in image engines | 0.3.0 |
| [Auto Web Search](tools/auto_web_search.py) | Automated web search using native or Perplexica search engines | 1.0.0 |
| [Memory Tools](tools/memory_tools.py) | Native tools to query and retrieve memories from the built-in memory system | 1.0.0 |

## Installation

### From Open WebUI Community (Recommended)

1. Navigate to the Open WebUI admin panel
2. Go to **Workspace > Functions** (for filters/actions/tools) or **Workspace > Pipelines** (for pipes)
3. Click **Import** and paste the raw URL of the extension file

### Manual Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/hfosse2/open-webui-extensions.git
   ```
2. Copy the desired extension file into the Open WebUI admin panel:
   - For filters: Workspace > Functions > Create > paste code
   - For tools: Workspace > Functions > Create > paste code
   - For actions: Workspace > Functions > Create > paste code
   - For pipes: Workspace > Functions > Create > paste code

## Extension Details

### Auto Memory (Filter)

Automatically identifies and stores valuable information from chats as Memories. Analyzes conversations, extracts key details, consolidates duplicates, and updates conflicting information.

**Configuration:**
- OpenAI-compatible API endpoint for memory processing
- Model selection for memory identification
- Related memory count and distance threshold
- Optional assistant response saving
- Configurable message analysis window

### Auto Claude (Pipeline)

A native Anthropic Claude manifold pipeline supporting all current Claude models including Opus 4.8, Opus 4.7, Opus 4.6, Sonnet 4.6, Sonnet 4.5, and Haiku 4.5.

**Features:**
- Extended thinking and adaptive thinking support
- Native tool/function calling with automatic execution
- Vision support with automatic image compression
- Streaming responses
- Configurable reasoning effort levels

### Auto Code Analysis (Tool)

Execute Python code in sandboxed environments with support for Jupyter (self-hosted) and E2B (cloud) backends.

**Features:**
- Persistent session directories across conversation turns
- Automatic file upload/download
- Image output detection and display
- Configurable execution timeout

### Auto Web Search (Tool)

Search the web using either the native Open WebUI search engine or Perplexica.

**Features:**
- Multiple search queries in a single call
- URL content fetching
- Citation generation for search results
- Configurable search backend

### Auto Image (Tool)

Generate and edit images using Open WebUI's built-in image generation engine.

**Features:**
- Text-to-image generation
- Image editing with AI
- Configurable size and steps
- Automatic image display in chat

### Memory Tools (Tool)

Query and retrieve memories from Open WebUI's built-in memory system using semantic search.

## Development

Extensions follow the Open WebUI 0.9.0+ plugin API:
- All database and model calls must be `async`/`await`
- Plugin entrypoints (`inlet`, `outlet`, `stream`, `pipe`, `action`, tool methods) are async
- Use `__event_emitter__` for status updates and file attachments
- Use Pydantic `BaseModel` for `Valves` (configuration)

## License

See individual extension documentation files for specific licensing terms.

## Support

For questions, issues, or feature requests, please [open an issue](https://github.com/hfosse2/open-webui-extensions/issues).
