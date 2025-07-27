import requests
from readability import Document
from ddgs import DDGS
import asyncio
import os
from typing import Any, Awaitable, Callable, List, Optional, Dict
import re

# Import the llama client
from llama_api_client import AsyncLlamaAPIClient

# ANSI color codes for better output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Copy the concurrent utilities directly here
class ProgressTracker:
    def __init__(self):
        self.calls_sent = 0
        self.calls_completed = 0
        self.errors = 0
        self.callbacks = []

    def register_callback(self, callback: Callable[[Dict[str, int]], None]):
        self.callbacks.append(callback)

    def update(self, sent=0, completed=0, errors=0):
        self.calls_sent += sent
        self.calls_completed += completed
        self.errors += errors
        for cb in self.callbacks:
            cb({
                'calls_sent': self.calls_sent,
                'calls_completed': self.calls_completed,
                'errors': self.errors
            })

async def async_batch_runner(
    callables: List[Callable[[], Awaitable[Any]]],
    batch_size: int = 100,
    tracker: Optional[ProgressTracker] = None,
    loop_fn: Optional[Callable[[List[Any]], List[Callable[[], Awaitable[Any]]]]] = None,
    max_loops: int = 5
) -> List[Any]:
    results = []
    to_run = callables
    loops = 0
    while to_run and (max_loops is None or loops < max_loops):
        batch = to_run[:batch_size]
        to_run = to_run[batch_size:]
        if tracker:
            tracker.update(sent=len(batch))
        tasks = [asyncio.create_task(fn()) for fn in batch]
        batch_results = []
        for task in asyncio.as_completed(tasks):
            try:
                res = await task
                batch_results.append(res)
                if tracker:
                    tracker.update(completed=1)
            except Exception:
                if tracker:
                    tracker.update(errors=1)
        results.extend(batch_results)
        if loop_fn:
            to_run += loop_fn(batch_results)
        loops += 1
    return results

# Set your API key as an environment variable or directly here
API_KEY = os.getenv("LLAMA_API_KEY")
if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
    raise RuntimeError("Please set your LLAMA_API_KEY environment variable with your Llama API key.")


# Initialize the Llama API client
client = AsyncLlamaAPIClient(api_key=API_KEY)


# Fetch real web results using DuckDuckGo
def duckduckgo_web_search(query: str, max_results: int = 10):
    ddgs = DDGS()
    return list(ddgs.text(query, max_results=max_results))


# Fetch and summarize the actual web page content
async def llama_summarize_web_result(result: dict):
    url = result.get('href') or result.get('url')
    snippet = result.get('body') or result.get('snippet') or ''
    title = result.get('title') or ''
    page_text = None
    if url:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.ok and 'text/html' in resp.headers.get('Content-Type', ''):
                doc = Document(resp.text)
                page_text = doc.summary(html_partial=False)
                # Remove HTML tags
                import re
                page_text = re.sub('<[^<]+?>', '', page_text)
                # Truncate to avoid token overflow
                page_text = page_text[:6000]
        except Exception:
            page_text = None
    if page_text:
        prompt = f"Summarize the following web page for a user deciding what to click next. Title: {title}\nURL: {url}\nContent: {page_text}"
    else:
        prompt = f"Summarize this web result for a user deciding what to click next. Title: {title}\nSnippet: {snippet}\nURL: {url}"

    response = await client.chat.completions.create(
        model="Llama-3.3-70B-Instruct",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=512,
        temperature=0.7,
    )

    return {
        "title": title,
        "url": url,
        "summary": response.completion_message.content.text
    }


def summarize_results(results):
    """Format results in a more readable way with better visual separation"""
    formatted_results = []
    for r in results:
        title = r.get('title', 'No Title')
        summary = r.get('summary', 'No summary available')
        url = r.get('url', 'No URL')

        # Wrap text to reasonable length
        summary_lines = []
        words = summary.split()
        current_line = ""
        for word in words:
            if len(current_line + word) < 80:
                current_line += word + " "
            else:
                summary_lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            summary_lines.append(current_line.strip())

        formatted_summary = "\n   ".join(summary_lines)

        formatted_result = f"""{Colors.BOLD}{Colors.OKBLUE}📄 {title}{Colors.ENDC}
   {formatted_summary}
   {Colors.OKCYAN}🔗 {url}{Colors.ENDC}"""
        formatted_results.append(formatted_result)

    return formatted_results

def print_header(text):
    """Print a styled header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}  {text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")

def print_progress_bar(current, total, prefix="Progress"):
    """Print a simple progress bar"""
    bar_length = 30
    filled_length = int(bar_length * current / total) if total > 0 else 0
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    percent = (current / total) * 100 if total > 0 else 0
    print(f"\r{Colors.OKGREEN}{prefix}: |{bar}| {current}/{total} ({percent:.1f}%){Colors.ENDC}", end='', flush=True)

async def interactive_search():
    tracker = ProgressTracker()
    def print_progress(stats):
        if stats['calls_sent'] > 0:
            print_progress_bar(stats['calls_completed'], stats['calls_sent'], "Processing")
    tracker.register_callback(print_progress)

    print_header("🔍 PARALLEL WEB SEARCH WITH LLAMA AI")
    print(f"{Colors.OKCYAN}Welcome! Enter your search queries to get AI-powered summaries of web results.{Colors.ENDC}")
    print(f"{Colors.WARNING}Type 'exit' to quit at any time.{Colors.ENDC}\n")

    while True:
        try:
            user_input = input(f"{Colors.BOLD}🔍 Enter your search query: {Colors.ENDC}").strip()
            if user_input.lower() == 'exit':
                print(f"\n{Colors.OKGREEN}Thanks for using Parallel Web Search! Goodbye! 👋{Colors.ENDC}")
                break

            if not user_input:
                print(f"{Colors.WARNING}Please enter a search query.{Colors.ENDC}")
                continue

            print(f"\n{Colors.OKBLUE}🌐 Fetching web results for: '{user_input}'...{Colors.ENDC}")
            web_results = duckduckgo_web_search(user_input, max_results=8)

            if not web_results:
                print(f"{Colors.FAIL}❌ No web results found. Try another query.{Colors.ENDC}")
                continue

            print(f"{Colors.OKGREEN}✅ Found {len(web_results)} results! Summarizing with Llama AI...{Colors.ENDC}")
            callables = [lambda r=r: llama_summarize_web_result(r) for r in web_results]
            results = await async_batch_runner(
                callables,
                batch_size=8,
                tracker=tracker,
                loop_fn=None,
                max_loops=1
            )

            print(f"\n{Colors.OKGREEN}✅ Processing complete!{Colors.ENDC}")
            print_header("📊 SEARCH RESULTS")
            summaries = summarize_results(results)
            for idx, summary in enumerate(summaries, 1):
                print(f"\n{Colors.BOLD}{idx}.{Colors.ENDC} {summary}")

            print(f"\n{Colors.BOLD}0.{Colors.ENDC} {Colors.OKCYAN}🔄 Enter a new search query{Colors.ENDC}")

            choice = input(f"\n{Colors.BOLD}Pick an option to drill down (0-{len(results)}): {Colors.ENDC}").strip()
            if choice == '0':
                continue

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    selected_result = results[idx]
                    next_query = selected_result["url"] or selected_result["title"]
                    print(f"\n{Colors.HEADER}🔍 Drilling down into: {selected_result['title']}{Colors.ENDC}")
                    print(f"{Colors.OKCYAN}🔗 {next_query}{Colors.ENDC}")

                    web_results = duckduckgo_web_search(next_query, max_results=8)
                    if web_results:
                        print(f"\n{Colors.OKGREEN}✅ Found {len(web_results)} related results! Summarizing...{Colors.ENDC}")
                        callables = [lambda r=r: llama_summarize_web_result(r) for r in web_results]
                        results = await async_batch_runner(
                            callables,
                            batch_size=8,
                            tracker=tracker,
                            loop_fn=None,
                            max_loops=1
                        )

                        print(f"\n{Colors.OKGREEN}✅ Processing complete!{Colors.ENDC}")
                        print_header("📊 DRILL-DOWN RESULTS")
                        summaries = summarize_results(results)
                        for idx2, summary in enumerate(summaries, 1):
                            print(f"\n{Colors.BOLD}{idx2}.{Colors.ENDC} {summary}")
                    else:
                        print(f"{Colors.FAIL}❌ No related results found.{Colors.ENDC}")
                else:
                    print(f"{Colors.FAIL}❌ Invalid choice. Please enter a number between 0 and {len(results)}.{Colors.ENDC}")
            except ValueError:
                print(f"{Colors.FAIL}❌ Invalid input. Please enter a number.{Colors.ENDC}")

        except KeyboardInterrupt:
            print(f"\n\n{Colors.WARNING}🛑 Search interrupted. Goodbye!{Colors.ENDC}")
            break
        except Exception as e:
            print(f"{Colors.FAIL}❌ An error occurred: {e}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}Let's try again...{Colors.ENDC}")

if __name__ == "__main__":
    asyncio.run(interactive_search())
