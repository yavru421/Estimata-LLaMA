import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import requests
from readability import Document
from ddgs import DDGS
import asyncio
import os
import sys
from typing import Any, Awaitable, Callable, List, Optional, Dict
import time
import webbrowser
import json
from datetime import datetime
import psutil
import tiktoken

# Import the llama client
from llama_api_client import AsyncLlamaAPIClient

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

# Set your API key
API_KEY = os.getenv("LLAMA_API_KEY")
if not API_KEY:
    raise RuntimeError("Please set your LLAMA_API_KEY environment variable.")

# Initialize the Llama API client
client = AsyncLlamaAPIClient(api_key=API_KEY)

# Performance Metrics Tracker
class PerformanceMetrics:
    def __init__(self):
        self.reset()
        self.session_start_time = time.time()

    def reset(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_tokens_sent = 0
        self.total_tokens_received = 0
        self.total_api_cost = 0.0
        self.total_search_time = 0.0
        self.total_processing_time = 0.0
        self.web_pages_fetched = 0
        self.web_pages_failed = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.search_history = []
        self.request_times = []

    def add_request(self, success=True, tokens_sent=0, tokens_received=0, processing_time=0.0):
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        self.total_tokens_sent += tokens_sent
        self.total_tokens_received += tokens_received
        self.total_processing_time += processing_time
        self.request_times.append(processing_time)

        # Estimate cost (rough estimate for Llama API)
        self.total_api_cost += (tokens_sent * 0.0001) + (tokens_received * 0.0002)

    def add_search(self, query, results_count, search_time):
        self.search_history.append({
            'query': query,
            'results_count': results_count,
            'search_time': search_time,
            'timestamp': datetime.now().isoformat()
        })
        self.total_search_time += search_time

    def add_web_fetch(self, success=True):
        self.web_pages_fetched += 1
        if not success:
            self.web_pages_failed += 1

    def get_average_request_time(self):
        return sum(self.request_times) / len(self.request_times) if self.request_times else 0

    def get_success_rate(self):
        return (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0

    def get_uptime(self):
        return time.time() - self.session_start_time

    def get_system_metrics(self):
        try:
            process = psutil.Process()
            return {
                'cpu_percent': process.cpu_percent(),
                'memory_mb': process.memory_info().rss / 1024 / 1024,
                'memory_percent': process.memory_percent(),
                'threads': process.num_threads()
            }
        except:
            return {
                'cpu_percent': 0,
                'memory_mb': 0,
                'memory_percent': 0,
                'threads': 0
            }

# Global metrics instance
metrics = PerformanceMetrics()

class WebSearchGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 Parallel Web Search - GUI/CLI Hybrid")
        self.root.geometry("1200x800")

        # Configure colors
        self.colors = {
            'bg': '#1e1e1e',
            'fg': '#ffffff',
            'accent': '#0078d4',
            'success': '#16c60c',
            'warning': '#ffb900',
            'error': '#d13438',
            'secondary': '#8e8e93'
        }

        self.root.configure(bg=self.colors['bg'])

        # Create main frame
        main_frame = ttk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Configure style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Custom.TFrame', background=self.colors['bg'])

        # Initialize data structures first
        # Queue for thread communication
        self.message_queue = queue.Queue()
        self.results_queue = queue.Queue()

        # Current search results and navigation
        self.current_results = []
        self.result_history = []  # Stack for back navigation
        self.current_query = ""

        # Research organization (Goose) - Define categories first
        self.goose_categories = ["General", "Important", "Follow-up", "Archive"]
        self.goose_items = []

        # Create main paned window (horizontal)
        self.main_paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # Create left paned window (vertical for CLI and metrics)
        self.left_paned = ttk.PanedWindow(self.main_paned, orient=tk.VERTICAL)
        self.main_paned.add(self.left_paned, weight=1)

        # Left pane - CLI Input
        self.create_cli_pane()

        # Metrics pane
        self.create_metrics_pane()

        # Right pane - GUI Output
        self.create_gui_pane()

        # Start checking for messages
        self.check_messages()

        # Start CLI thread
        self.cli_thread = threading.Thread(target=self.cli_loop, daemon=True)
        self.cli_thread.start()

    def create_cli_pane(self):
        # CLI Frame
        cli_frame = ttk.Frame(self.left_paned)
        self.left_paned.add(cli_frame, weight=2)

        # CLI Header
        cli_header = ttk.Label(cli_frame, text="🖥️ CLI Input", font=('Consolas', 12, 'bold'))
        cli_header.pack(pady=5)

        # CLI Text area
        self.cli_text = scrolledtext.ScrolledText(
            cli_frame,
            height=15,
            width=50,
            font=('Consolas', 10),
            bg='#2d2d2d',
            fg='#00ff00',
            insertbackground='#00ff00',
            wrap=tk.WORD
        )
        self.cli_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Input frame
        input_frame = ttk.Frame(cli_frame)
        input_frame.pack(fill=tk.X, padx=5, pady=5)

        # Command input
        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(
            input_frame,
            textvariable=self.command_var,
            font=('Consolas', 10)
        )
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.command_entry.bind('<Return>', self.send_command)

        # Send button
        send_btn = ttk.Button(input_frame, text="Send", command=self.send_command)
        send_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Progress bar
        self.progress = ttk.Progressbar(cli_frame, mode='determinate')
        self.progress.pack(fill=tk.X, padx=5, pady=5)

        # Status label
        self.status_label = ttk.Label(cli_frame, text="Ready", font=('Consolas', 9))
        self.status_label.pack(pady=2)

    def create_metrics_pane(self):
        # Metrics Frame
        metrics_frame = ttk.Frame(self.left_paned)
        self.left_paned.add(metrics_frame, weight=1)

        # Metrics Header
        metrics_header = ttk.Label(metrics_frame, text="📊 Performance Metrics", font=('Consolas', 11, 'bold'))
        metrics_header.pack(pady=5)

        # Create notebook for different metric categories
        self.metrics_notebook = ttk.Notebook(metrics_frame)
        self.metrics_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # API Metrics Tab
        api_frame = ttk.Frame(self.metrics_notebook)
        self.metrics_notebook.add(api_frame, text="API")

        # API Metrics
        self.api_metrics_text = tk.Text(
            api_frame,
            height=8,
            width=40,
            font=('Consolas', 8),
            bg='#f0f0f0',
            fg='#000000',
            wrap=tk.WORD
        )
        self.api_metrics_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # System Metrics Tab
        system_frame = ttk.Frame(self.metrics_notebook)
        self.metrics_notebook.add(system_frame, text="System")

        self.system_metrics_text = tk.Text(
            system_frame,
            height=8,
            width=40,
            font=('Consolas', 8),
            bg='#f0f0f0',
            fg='#000000',
            wrap=tk.WORD
        )
        self.system_metrics_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Search History Tab
        history_frame = ttk.Frame(self.metrics_notebook)
        self.metrics_notebook.add(history_frame, text="History")

        self.history_text = tk.Text(
            history_frame,
            height=8,
            width=40,
            font=('Consolas', 8),
            bg='#f0f0f0',
            fg='#000000',
            wrap=tk.WORD
        )
        self.history_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Goose Research Tab
        goose_frame = ttk.Frame(self.metrics_notebook)
        self.metrics_notebook.add(goose_frame, text="🪿 Goose")

        # Goose controls
        goose_controls = ttk.Frame(goose_frame)
        goose_controls.pack(fill=tk.X, padx=5, pady=5)

        # Category filter
        ttk.Label(goose_controls, text="Category:").pack(side=tk.LEFT)
        self.goose_category_var = tk.StringVar(value="All")
        category_combo = ttk.Combobox(
            goose_controls,
            textvariable=self.goose_category_var,
            values=["All"] + self.goose_categories,
            state="readonly",
            width=10
        )
        category_combo.pack(side=tk.LEFT, padx=5)
        category_combo.bind('<<ComboboxSelected>>', lambda e: self.update_goose_display())

        # Clear button
        clear_btn = ttk.Button(goose_controls, text="Clear All", command=self.clear_goose)
        clear_btn.pack(side=tk.RIGHT)

        # Export button
        export_btn = ttk.Button(goose_controls, text="Export", command=self.export_goose)
        export_btn.pack(side=tk.RIGHT, padx=5)

        # Goose items display
        self.goose_text = tk.Text(
            goose_frame,
            height=6,
            width=40,
            font=('Consolas', 8),
            bg='#f0f0f0',
            fg='#000000',
            wrap=tk.WORD
        )
        self.goose_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Reset button
        reset_btn = ttk.Button(metrics_frame, text="Reset Metrics", command=self.reset_metrics)
        reset_btn.pack(pady=5)

        # Auto-update metrics
        self.update_metrics_display()

    def reset_metrics(self):
        """Reset all metrics"""
        metrics.reset()
        self.cli_print("📊 Metrics reset!")
        self.update_metrics_display()

    def update_metrics_display(self):
        """Update the metrics display"""
        try:
            # API Metrics
            api_text = f"""🔥 API METRICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Total Requests: {metrics.total_requests}
✅ Successful: {metrics.successful_requests}
❌ Failed: {metrics.failed_requests}
📈 Success Rate: {metrics.get_success_rate():.1f}%

🪙 TOKENS & COST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📤 Tokens Sent: {metrics.total_tokens_sent:,}
📥 Tokens Received: {metrics.total_tokens_received:,}
💰 Estimated Cost: ${metrics.total_api_cost:.4f}

⏱️ TIMING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Avg Request Time: {metrics.get_average_request_time():.2f}s
🔍 Total Search Time: {metrics.total_search_time:.2f}s
🤖 Total Processing: {metrics.total_processing_time:.2f}s

🌐 WEB FETCHING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 Pages Fetched: {metrics.web_pages_fetched}
❌ Failed Fetches: {metrics.web_pages_failed}
📊 Success Rate: {((metrics.web_pages_fetched - metrics.web_pages_failed) / max(metrics.web_pages_fetched, 1) * 100):.1f}%"""

            self.api_metrics_text.delete(1.0, tk.END)
            self.api_metrics_text.insert(tk.END, api_text)

            # System Metrics
            sys_metrics = metrics.get_system_metrics()
            uptime = metrics.get_uptime()
            system_text = f"""💻 SYSTEM PERFORMANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 CPU Usage: {sys_metrics['cpu_percent']:.1f}%
🧠 Memory: {sys_metrics['memory_mb']:.1f} MB ({sys_metrics['memory_percent']:.1f}%)
🧵 Threads: {sys_metrics['threads']}

⏰ SESSION INFO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🕐 Uptime: {uptime/60:.1f} minutes
🔄 Requests/Min: {(metrics.total_requests / max(uptime/60, 1)):.1f}
⚡ Avg Load: {(metrics.total_processing_time / max(uptime, 1) * 100):.1f}%

🎯 EFFICIENCY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 Cache Hit Rate: {((metrics.cache_hits / max(metrics.cache_hits + metrics.cache_misses, 1)) * 100):.1f}%
🚀 Tokens/Second: {(metrics.total_tokens_received / max(metrics.total_processing_time, 1)):.1f}
💸 Cost/Request: ${(metrics.total_api_cost / max(metrics.total_requests, 1)):.4f}"""

            self.system_metrics_text.delete(1.0, tk.END)
            self.system_metrics_text.insert(tk.END, system_text)

            # Search History
            history_text = "🔍 SEARCH HISTORY\n" + "━" * 40 + "\n"
            for i, search in enumerate(metrics.search_history[-10:], 1):  # Show last 10 searches
                timestamp = datetime.fromisoformat(search['timestamp']).strftime('%H:%M:%S')
                history_text += f"{i:2d}. [{timestamp}] {search['query'][:30]}{'...' if len(search['query']) > 30 else ''}\n"
                history_text += f"     📊 {search['results_count']} results in {search['search_time']:.2f}s\n\n"

            if not metrics.search_history:
                history_text += "No searches yet. Start searching to see history!"

            self.history_text.delete(1.0, tk.END)
            self.history_text.insert(tk.END, history_text)

        except Exception as e:
            pass  # Silently handle any display errors

        # Schedule next update
        self.root.after(2000, self.update_metrics_display)  # Update every 2 seconds

    def add_to_goose(self, result, category="General"):
        """Add a result to the Goose research collection"""
        goose_item = {
            'id': len(self.goose_items) + 1,
            'title': result.get('title', 'No Title'),
            'url': result.get('url', ''),
            'summary': result.get('summary', ''),
            'category': category,
            'timestamp': datetime.now().isoformat(),
            'query': self.current_query
        }
        self.goose_items.append(goose_item)
        self.update_goose_display()
        self.cli_print(f"🪿 Added to Goose: {goose_item['title']}")

    def update_goose_display(self):
        """Update the Goose display"""
        try:
            filter_category = self.goose_category_var.get()

            # Filter items
            if filter_category == "All":
                filtered_items = self.goose_items
            else:
                filtered_items = [item for item in self.goose_items if item['category'] == filter_category]

            # Build display text
            goose_text = f"🪿 GOOSE RESEARCH COLLECTION\n"
            goose_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            goose_text += f"📊 Total Items: {len(self.goose_items)} | Showing: {len(filtered_items)}\n"
            goose_text += f"🏷️ Filter: {filter_category}\n\n"

            if not filtered_items:
                goose_text += "No items in Goose yet. Click 'Add to Goose' on search results!"
            else:
                for item in filtered_items[-20:]:  # Show last 20 items
                    timestamp = datetime.fromisoformat(item['timestamp']).strftime('%m/%d %H:%M')
                    goose_text += f"🎯 #{item['id']} [{timestamp}] {item['category']}\n"
                    goose_text += f"   {item['title'][:50]}{'...' if len(item['title']) > 50 else ''}\n"
                    goose_text += f"   🔍 Query: {item['query'][:30]}{'...' if len(item['query']) > 30 else ''}\n"
                    goose_text += f"   🔗 {item['url'][:40]}{'...' if len(item['url']) > 40 else ''}\n\n"

            self.goose_text.delete(1.0, tk.END)
            self.goose_text.insert(tk.END, goose_text)

        except Exception as e:
            pass  # Silently handle display errors

    def clear_goose(self):
        """Clear all Goose items"""
        self.goose_items = []
        self.update_goose_display()
        self.cli_print("🪿 Cleared all Goose items!")

    def export_goose(self):
        """Export Goose items to JSON"""
        try:
            import json
            from tkinter import filedialog

            if not self.goose_items:
                self.cli_print("🪿 No items to export!")
                return

            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="Export Goose Research"
            )

            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.goose_items, f, indent=2, ensure_ascii=False)
                self.cli_print(f"🪿 Exported {len(self.goose_items)} items to {filename}")

        except Exception as e:
            self.cli_print(f"🪿 Export error: {str(e)}")

    def go_back(self):
        """Go back to previous search results"""
        if self.result_history:
            previous_state = self.result_history.pop()
            self.current_results = previous_state['results']
            self.current_query = previous_state['query']
            self.display_results(self.current_results)
            self.cli_print(f"⬅️ Back to: {self.current_query}")
        else:
            self.cli_print("⬅️ No previous results to go back to!")

    def save_current_state(self):
        """Save current state to history"""
        if self.current_results:
            state = {
                'results': self.current_results.copy(),
                'query': self.current_query,
                'timestamp': datetime.now().isoformat()
            }
            self.result_history.append(state)
            # Keep only last 10 states
            if len(self.result_history) > 10:
                self.result_history.pop(0)

    def create_gui_pane(self):
        # GUI Frame
        gui_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(gui_frame, weight=2)

        # GUI Header with navigation
        header_frame = ttk.Frame(gui_frame)
        header_frame.pack(fill=tk.X, pady=5)

        # Back button
        self.back_btn = ttk.Button(header_frame, text="⬅️ Back", command=self.go_back)
        self.back_btn.pack(side=tk.LEFT, padx=5)

        # Title
        gui_header = ttk.Label(header_frame, text="🌐 Search Results", font=('Segoe UI', 12, 'bold'))
        gui_header.pack(side=tk.LEFT, padx=10)

        # Current query display
        self.query_label = ttk.Label(header_frame, text="", font=('Segoe UI', 10, 'italic'))
        self.query_label.pack(side=tk.LEFT, padx=10)

        # Results frame with scrollbar
        results_frame = ttk.Frame(gui_frame)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Canvas for scrolling
        self.canvas = tk.Canvas(results_frame, bg='#f0f0f0')
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mousewheel to canvas
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def send_command(self, event=None):
        command = self.command_var.get().strip()
        if command:
            self.message_queue.put(('command', command))
            self.command_var.set("")
            self.cli_print(f"🔍 Search: {command}")

    def cli_print(self, message):
        """Print message to CLI pane"""
        self.cli_text.insert(tk.END, message + "\n")
        self.cli_text.see(tk.END)

    def update_status(self, message):
        """Update status label"""
        self.status_label.config(text=message)

    def update_progress(self, current, total):
        """Update progress bar"""
        if total > 0:
            progress_value = (current / total) * 100
            self.progress['value'] = progress_value

    def display_results(self, results):
        """Display search results in GUI pane"""
        # Clear previous results
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.current_results = results

        # Update back button state
        self.back_btn.config(state=tk.NORMAL if self.result_history else tk.DISABLED)

        # Update query label
        self.query_label.config(text=f"Query: {self.current_query}")

        if not results:
            no_results = ttk.Label(
                self.scrollable_frame,
                text="No results found. Try another search.",
                font=('Segoe UI', 10),
                foreground='red'
            )
            no_results.pack(pady=20)
            return

        # Display each result
        for i, result in enumerate(results, 1):
            self.create_result_card(i, result)

        # Update Goose display
        self.update_goose_display()

    def create_result_card(self, index, result):
        """Create a card for each search result"""
        # Main card frame
        card_frame = ttk.Frame(self.scrollable_frame, relief='raised', borderwidth=1)
        card_frame.pack(fill=tk.X, padx=5, pady=8)

        # Header frame
        header_frame = ttk.Frame(card_frame)
        header_frame.pack(fill=tk.X, padx=10, pady=5)

        # Index and title
        index_label = ttk.Label(
            header_frame,
            text=f"{index}.",
            font=('Segoe UI', 12, 'bold'),
            foreground='#0078d4'
        )
        index_label.pack(side=tk.LEFT)

        title_label = ttk.Label(
            header_frame,
            text=result.get('title', 'No Title'),
            font=('Segoe UI', 11, 'bold'),
            wraplength=600
        )
        title_label.pack(side=tk.LEFT, padx=(5, 0))

        # URL frame
        url_frame = ttk.Frame(card_frame)
        url_frame.pack(fill=tk.X, padx=10, pady=2)

        url_text = result.get('url', '')
        if url_text:
            url_label = ttk.Label(
                url_frame,
                text=f"🔗 {url_text}",
                font=('Segoe UI', 9),
                foreground='#0078d4',
                cursor='hand2'
            )
            url_label.pack(anchor=tk.W)
            url_label.bind("<Button-1>", lambda e, url=url_text: webbrowser.open(url))

        # Summary frame
        summary_frame = ttk.Frame(card_frame)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)

        summary_label = ttk.Label(
            summary_frame,
            text=result.get('summary', 'No summary available'),
            font=('Segoe UI', 10),
            wraplength=700,
            justify=tk.LEFT
        )
        summary_label.pack(anchor=tk.W)

        # Actions frame
        actions_frame = ttk.Frame(card_frame)
        actions_frame.pack(fill=tk.X, padx=10, pady=5)

        # Drill down button
        drill_btn = ttk.Button(
            actions_frame,
            text=f"🔍 Drill Down",
            command=lambda idx=index: self.drill_down(idx)
        )
        drill_btn.pack(side=tk.LEFT)

        # Add to Goose button with category dropdown
        goose_frame = ttk.Frame(actions_frame)
        goose_frame.pack(side=tk.LEFT, padx=(5, 0))

        # Category selection for Goose
        category_var = tk.StringVar(value="General")
        category_combo = ttk.Combobox(
            goose_frame,
            textvariable=category_var,
            values=self.goose_categories,
            state="readonly",
            width=10
        )
        category_combo.pack(side=tk.LEFT)

        # Add to Goose button
        goose_btn = ttk.Button(
            goose_frame,
            text="🪿 Add to Goose",
            command=lambda r=result, var=category_var: self.add_to_goose(r, var.get())
        )
        goose_btn.pack(side=tk.LEFT, padx=(2, 0))

        # Copy URL button
        if url_text:
            copy_btn = ttk.Button(
                actions_frame,
                text="📋 Copy URL",
                command=lambda url=url_text: self.copy_to_clipboard(url)
            )
            copy_btn.pack(side=tk.RIGHT)

        # Separator
        separator = ttk.Separator(self.scrollable_frame, orient='horizontal')
        separator.pack(fill=tk.X, padx=10, pady=2)

    def copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.cli_print(f"📋 Copied to clipboard: {text}")

    def drill_down(self, index):
        """Drill down into a specific result"""
        if 0 < index <= len(self.current_results):
            # Save current state before drilling down
            self.save_current_state()

            result = self.current_results[index - 1]
            query = result.get('url', result.get('title', ''))
            self.message_queue.put(('drill_down', query))
            self.cli_print(f"🔍 Drilling down into: {query}")

    def check_messages(self):
        """Check for messages from CLI thread"""
        try:
            while True:
                message_type, data = self.results_queue.get_nowait()

                if message_type == 'results':
                    self.display_results(data)
                elif message_type == 'status':
                    self.update_status(data)
                elif message_type == 'progress':
                    current, total = data
                    self.update_progress(current, total)
                elif message_type == 'cli_print':
                    self.cli_print(data)
                elif message_type == 'query_update':
                    self.current_query = data

        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self.check_messages)

    def cli_loop(self):
        """Main CLI loop running in separate thread"""
        asyncio.run(self.async_cli_loop())

    async def async_cli_loop(self):
        """Async CLI loop"""
        self.results_queue.put(('cli_print', "🚀 Parallel Web Search Started!"))
        self.results_queue.put(('cli_print', "💡 Type your search query and press Enter"))
        self.results_queue.put(('cli_print', "🔗 Click on URLs in the results to open them"))
        self.results_queue.put(('cli_print', "📝 Use the drill-down buttons to explore further"))
        self.results_queue.put(('cli_print', "=" * 50))

        while True:
            try:
                # Check for commands
                message_type, data = self.message_queue.get(timeout=0.1)

                if message_type == 'command':
                    await self.process_search(data)
                elif message_type == 'drill_down':
                    await self.process_search(data, is_drill_down=True)

            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

    async def process_search(self, query, is_drill_down=False):
        """Process search query"""
        if not query or query.lower() == 'exit':
            return

        search_start_time = time.time()

        # Update current query
        self.current_query = query
        self.results_queue.put(('query_update', query))

        try:
            # Update status
            action = "🔍 Drilling down" if is_drill_down else "🔍 Searching"
            self.results_queue.put(('status', f"{action} for: {query}"))
            self.results_queue.put(('cli_print', f"\n{action} for: {query}"))

            # Get web results
            self.results_queue.put(('cli_print', "📡 Fetching web results..."))
            web_results = await asyncio.get_event_loop().run_in_executor(
                None, self.duckduckgo_web_search, query, 8
            )

            if not web_results:
                self.results_queue.put(('cli_print', "❌ No web results found. Try another query."))
                self.results_queue.put(('status', "No results found"))
                return

            # Process with Llama
            self.results_queue.put(('cli_print', f"🤖 Processing {len(web_results)} results with Llama..."))

            # Create progress tracker
            tracker = ProgressTracker()
            tracker.register_callback(self.progress_callback)

            # Create callables for parallel processing
            callables = [lambda r=r: self.llama_summarize_web_result(r) for r in web_results]

            # Process results
            results = await async_batch_runner(
                callables,
                batch_size=8,
                tracker=tracker,
                loop_fn=None,
                max_loops=1
            )

            # Record search metrics
            search_time = time.time() - search_start_time
            metrics.add_search(query, len(results), search_time)

            # Display results
            self.results_queue.put(('results', results))
            self.results_queue.put(('cli_print', f"✅ Found {len(results)} results in {search_time:.2f}s!"))
            self.results_queue.put(('status', f"Found {len(results)} results"))

        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            self.results_queue.put(('cli_print', error_msg))
            self.results_queue.put(('status', "Error occurred"))

            # Record failed search
            search_time = time.time() - search_start_time
            metrics.add_search(query, 0, search_time)

    def progress_callback(self, stats):
        """Progress callback for tracking"""
        total = stats['calls_sent']
        completed = stats['calls_completed']
        errors = stats['errors']

        self.results_queue.put(('progress', (completed, total)))

        if total > 0:
            status = f"Processing: {completed}/{total} completed"
            if errors > 0:
                status += f" ({errors} errors)"
            self.results_queue.put(('status', status))

    def duckduckgo_web_search(self, query: str, max_results: int = 10):
        """Search DuckDuckGo"""
        try:
            ddgs = DDGS()
            return list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            self.results_queue.put(('cli_print', f"❌ Search error: {str(e)}"))
            return []

    async def llama_summarize_web_result(self, result: dict):
        """Summarize web result using Llama"""
        start_time = time.time()

        url = result.get('href') or result.get('url')
        snippet = result.get('body') or result.get('snippet') or ''
        title = result.get('title') or ''

        # Try to fetch full page content
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
                    page_text = page_text[:4000]  # Truncate
                    metrics.add_web_fetch(True)
                else:
                    metrics.add_web_fetch(False)
            except Exception:
                metrics.add_web_fetch(False)

        # Create prompt
        if page_text:
            prompt = f"Summarize this web page concisely for search results. Focus on key information.\n\nTitle: {title}\nURL: {url}\nContent: {page_text}"
        else:
            prompt = f"Summarize this search result concisely.\n\nTitle: {title}\nSnippet: {snippet}\nURL: {url}"

        # Estimate tokens (rough approximation)
        tokens_sent = len(prompt.split()) * 1.3  # Rough token estimate

        try:
            response = await client.chat.completions.create(
                model="Llama-3.3-70B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=300,
                temperature=0.7,
            )

            summary = response.completion_message.content.text
            tokens_received = len(summary.split()) * 1.3
            processing_time = time.time() - start_time

            # Record metrics
            metrics.add_request(
                success=True,
                tokens_sent=int(tokens_sent),
                tokens_received=int(tokens_received),
                processing_time=processing_time
            )

            return {
                "title": title,
                "url": url,
                "summary": summary
            }
        except Exception as e:
            processing_time = time.time() - start_time
            metrics.add_request(
                success=False,
                tokens_sent=int(tokens_sent),
                tokens_received=0,
                processing_time=processing_time
            )

            return {
                "title": title,
                "url": url,
                "summary": f"Error summarizing: {str(e)}"
            }

def main():
    # Check for API key
    if not os.getenv("LLAMA_API_KEY"):
        print("❌ Please set your LLAMA_API_KEY environment variable.")
        return

    # Create GUI
    root = tk.Tk()
    app = WebSearchGUI(root)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")

if __name__ == "__main__":
    main()
