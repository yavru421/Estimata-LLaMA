
"""
IntegrataLlama: Unified interface for chat, moderation, web search, and tool calls.
"""

import os
from llama_api_client import LlamaAPIClient, AsyncLlamaAPIClient

class IntegrataLlama:
    """
    Integrates chat, moderation, web search, and tool call functionalities.
    """
    def __init__(self):
        self.client = LlamaAPIClient()
        self.async_client = AsyncLlamaAPIClient(api_key=os.getenv("LLAMA_API_KEY"))

    def chat(self, message, stream=False, **kwargs):
        """Send a message to the chat model and return the response."""
        messages = [{"role": "user", "content": message}]
        response = self.client.chat.completions.create(
            model="Llama-4-Maverick-17B-128E-Instruct-FP8",
            messages=messages,
            max_completion_tokens=1024,
            temperature=0.7,
            stream=stream,
        )
        if stream:
            return "".join(chunk.event.delta.text for chunk in response)
        else:
            return response.completion_message.model_dump()

    def moderate(self, content):
        """Moderate content using the moderation endpoint."""
        messages = [{"role": "user", "content": content}]
        response = self.client.moderations.create(messages=messages)
        return response

    def web_search(self, query, max_results=8):
        """Perform a DuckDuckGo web search and summarize results with Llama."""
        from ddgs import DDGS
        import requests
        from readability import Document
        import time
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        summaries = []
        for result in results:
            url = result.get('href') or result.get('url')
            snippet = result.get('body') or result.get('snippet') or ''
            title = result.get('title') or ''
            page_text = None
            if url:
                try:
                    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.ok and 'text/html' in resp.headers.get('Content-Type', ''):
                        doc = Document(resp.text)
                        import re
                        page_text = re.sub('<[^<]+?>', '', doc.summary(html_partial=False))[:4000]
                except Exception:
                    pass
            if page_text:
                prompt = f"Summarize this web page concisely for search results. Focus on key information.\n\nTitle: {title}\nURL: {url}\nContent: {page_text}"
            else:
                prompt = f"Summarize this search result concisely.\n\nTitle: {title}\nSnippet: {snippet}\nURL: {url}"
            summary_resp = self.client.chat.completions.create(
                model="Llama-3.3-70B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=300,
                temperature=0.7,
            )
            summary = summary_resp.completion_message.content.text if hasattr(summary_resp.completion_message.content, 'text') else str(summary_resp.completion_message.content)
            summaries.append({"title": title, "url": url, "summary": summary})
        return summaries

    def tool_call(self, tool_name, *args, **kwargs):
        """Call a tool using the tool_call module's available functions."""
        # Only get_weather and run are available
        if tool_name == "get_weather":
            from context_files.tool_call import get_weather
            return get_weather(*args, **kwargs)
        elif tool_name == "run":
            from context_files.tool_call import run
            return run(*args, **kwargs)
        else:
            raise NotImplementedError(f"Tool '{tool_name}' is not implemented.")

if __name__ == "__main__":
    llama = IntegrataLlama()
    print("Chat:", llama.chat("Hello!"))
    print("Moderation:", llama.moderate("Some content to check."))
    print("Web Search:", llama.web_search("What is LLaMA?"))
    print("Tool Call (get_weather):", llama.tool_call("get_weather", "London, UK"))
