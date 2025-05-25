import aiohttp
import asyncio
import concurrent.futures
import json
import logging
import math
import os
import random
import re
import requests
import signal
import ssl
import threading
import time
import sqlite3
from bs4 import BeautifulSoup
from collections import defaultdict, deque
from colorama import Fore, Style, init
from copy import deepcopy
from datetime import datetime
from nltk.corpus import stopwords
from stem import Signal
from stem.control import Controller
from urllib.parse import urlparse, urlunparse, quote, unquote

from flask import Flask, render_template, request
from math import ceil


init(autoreset=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MAGENTA = "\033[38;2;127;255;212m"
CORAL = "\033[38;2;244;164;96m"
CYAN = "\033[38;2;135;206;235m"
YELLOW = "\033[38;2;255;255;153m"
GREEN = "\033[38;2;102;205;170m"
BLUE = "\033[38;2;70;130;180m"
RED = "\033[38;2;240;128;128m"
RESET = "\033[0m"

NSFW_KEYWORDS = [
    "quantum miner","Bitcoin Quantum Miner", "dt6dt", "jfif","Free Bitcoin", "Free Bitcoins", "Bitcoin Generator", "bitcoin generator", "jfif c c u", "png ihdr", "Bitcoin Walet Market", "bitcoin walet market", "deephole", "jfif creator gd jpeg", "double","sex", "nude", "erotic", "xxx", "kid", "explicit", "son", "baby", "daughter", "censoredporn", "preteen",
    "gore", "violence", "bloody", "murder", "rape", "abuse", "child", "mom", "dad", "incest", "jailbait", "pedo", "young", "teen", "girl", "boy", "porn", "censoredPorn", "loli"
]

class SQLiteManager:
    def __init__(self, db_name='tor_search.db'):
        self.db_name = db_name
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Establishes a connection to the SQLite database."""
        if self.conn is None:
            try:
                self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
                self.conn.row_factory = sqlite3.Row # Allows accessing columns by name
                print(f"{GREEN}🗄️ Connected to SQLite database: {self.db_name}{RESET}")
            except sqlite3.Error as e:
                print(f"{RED}❗ Error connecting to SQLite: {e}{RESET}")
                self.conn = None

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            print(f"{YELLOW}🗄️ SQLite database connection closed.{RESET}")

    def create_tables(self):
        """Creates necessary tables if they don't exist."""
        if not self.conn:
            print(f"{RED}❗ Cannot create tables: No database connection.{RESET}")
            return

        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    content TEXT,
                    title TEXT,
                    date TEXT,
                    metadata TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reverse_index (
                    term TEXT NOT NULL,
                    doc_id INTEGER NOT NULL,
                    positions TEXT, -- Storing positions as JSON string
                    PRIMARY KEY (term, doc_id),
                    FOREIGN KEY (doc_id) REFERENCES links(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS link_relationships (
                    from_url TEXT NOT NULL,
                    to_url TEXT NOT NULL,
                    PRIMARY KEY (from_url, to_url)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS crawled_sites (
                    url TEXT PRIMARY KEY NOT NULL,
                    last_checked TEXT,
                    response_time REAL,
                    result TEXT,
                    status TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS discovered_onion_links (
                    url TEXT PRIMARY KEY NOT NULL
                )
            ''')
            self.conn.commit()
            print(f"{GREEN}✅ SQLite tables created/verified.{RESET}")
        except sqlite3.Error as e:
            print(f"{RED}❗ Error creating tables: {e}{RESET}")

    def _execute_query(self, query, params=(), fetch_one=False, fetch_all=False):
        """Helper for executing SQL queries."""
        if not self.conn:
            print(f"{RED}❗ No database connection to execute query.{RESET}")
            return None

        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            if fetch_one:
                return cursor.fetchone()
            if fetch_all:
                return cursor.fetchall()
            return cursor.lastrowid 
        except sqlite3.Error as e:
            print(f"{RED}❗ SQLite query error: {e} | Query: {query} | Params: {params}{RESET}")
            return None

class TorSession:
    def __init__(self, tor_password=None, port=9051, proxy_port=9050, pool_connections=100, pool_maxsize=100):
        self.tor_password = tor_password
        self.port = port
        self.proxy_port = proxy_port
        self.session = None
        self.ssl_context = ssl.create_default_context()
        self.pool_connections = pool_connections
        self.pool_maxsize = pool_maxsize
        self.controller = None
    def connect(self):
        attempt = 0
        while self.session is None and attempt < 5:
            try:
                self.controller = Controller.from_port(port=self.port)
                if self.tor_password:
                    self.controller.authenticate(password=self.tor_password)
                else:
                    self.controller.authenticate()
                self.controller.signal(Signal.NEWNYM)
                print(f"{CYAN}🔗 TOR Session established with SSL support on port {self.port}{RESET}")

                self.session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(pool_connections=self.pool_connections, pool_maxsize=self.pool_maxsize)
                self.session.mount('http://', adapter)
                self.session.mount('https://', adapter)
                self.session.proxies = {
                    'http': f'socks5h://127.0.0.1:{self.proxy_port}',
                    'https': f'socks5h://127.0.0.1:{self.proxy_port}'
                }
            except Exception as e:
                print(f"{RED}❗ Error: Failed to connect to TOR on port {self.port}: {e}{RESET}")
                attempt += 1
                self.controller = None 
                time.sleep(5) 

    def _session_is_valid(self):
        try:
            test_url = "http://example.com"
            response = self.session.get(test_url, timeout=75)
            return response.status_code == 200
        except:
            return False

    def get_session(self):
        if not self.session or not self._session_is_valid():
            self.connect()
        return self.session

    def close_controller(self):
        if self.controller:
            try:
                self.controller.close()
                print(f"{YELLOW}⚠️ TOR Controller on port {self.port} closed.{RESET}")
            except Exception as e:
                print(f"{RED}❗ Error: Failed to close TOR Controller on port {self.port}: {e}{RESET}")

class LinkIndexManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def insert_link(self, url, content, title=None, date=None, metadata=None):
        existing_link = self.db_manager._execute_query(
            "SELECT id FROM links WHERE url = ?", (url,), fetch_one=True
        )
        if existing_link:
            doc_id = existing_link['id']
            self.db_manager._execute_query(
                "UPDATE links SET content = ?, title = ?, date = ?, metadata = ? WHERE id = ?",
                (content, title, date, json.dumps(metadata) if metadata else None, doc_id)
            )
            print(f"{GREEN}✅ Link updated: {url} (ID: {doc_id}){RESET}")
            return doc_id
        else:
            doc_id = self.db_manager._execute_query(
                "INSERT INTO links (url, content, title, date, metadata) VALUES (?, ?, ?, ?, ?)",
                (url, content, title, date, json.dumps(metadata) if metadata else None)
            )
            if doc_id:
                print(f"{GREEN}✅✅✅ Link indexed: {url} (ID: {doc_id}){RESET}")
            else:
                print(f"{RED}❗ Error: Failed to insert link: {url}{RESET}")
            return doc_id

    def get_link_id(self, url):
        result = self.db_manager._execute_query(
            "SELECT id FROM links WHERE url = ?", (url,), fetch_one=True
        )
        return result['id'] if result else None

    def get_all_links(self):
        links_data = self.db_manager._execute_query(
            "SELECT id, url, content, title, date, metadata FROM links", fetch_all=True
        )
        return [dict(link) for link in links_data] if links_data else []

    def get_link_by_id(self, link_id):
        link_data = self.db_manager._execute_query(
            "SELECT id, url, content, title, date, metadata FROM links WHERE id = ?", (link_id,), fetch_one=True
        )
        return dict(link_data) if link_data else None

class ReverseContentIndexManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def update_reverse_index(self, doc_id, term, positions):
        positions_json = json.dumps(positions)
        self.db_manager._execute_query(
            "INSERT OR REPLACE INTO reverse_index (term, doc_id, positions) VALUES (?, ?, ?)",
            (term, doc_id, positions_json)
        )
        print(f"{BLUE}🔍 Reverse index updated for term '{term}' in document ID: {doc_id}{RESET}")

    def get_positions_for_term_doc(self, term, doc_id):
        result = self.db_manager._execute_query(
            "SELECT positions FROM reverse_index WHERE term = ? AND doc_id = ?",
            (term, doc_id), fetch_one=True
        )
        return json.loads(result['positions']) if result and result['positions'] else []

    def get_docs_for_term(self, term):
        results = self.db_manager._execute_query(
            "SELECT doc_id, positions FROM reverse_index WHERE term = ?",
            (term,), fetch_all=True
        )
        return {row['doc_id']: json.loads(row['positions']) for row in results} if results else {}

    def get_all_terms(self):
        results = self.db_manager._execute_query(
            "SELECT DISTINCT term FROM reverse_index", fetch_all=True
        )
        return [row['term'] for row in results] if results else []

class LinkRelationshipManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def add_relationship(self, from_url, to_url):
        self.db_manager._execute_query(
            "INSERT OR IGNORE INTO link_relationships (from_url, to_url) VALUES (?, ?)",
            (from_url, to_url)
        )
        print(f"{CYAN}🔗 Relationship added: {from_url} -> {to_url}{RESET}")

    def get_relationships_from(self, from_url):
        results = self.db_manager._execute_query(
            "SELECT to_url FROM link_relationships WHERE from_url = ?", (from_url,), fetch_all=True
        )
        return [row['to_url'] for row in results] if results else []

class LinkCrawler(threading.Thread):
    def __init__(self, tor_session, link_index_manager, reverse_index_manager, relationship_manager, seed_urls, db_manager, depth=2, retries=3):
        threading.Thread.__init__(self)
        self.session = tor_session.get_session()
        self.link_index_manager = link_index_manager
        self.reverse_index_manager = reverse_index_manager
        self.relationship_manager = relationship_manager
        self.db_manager = db_manager
        self.depth = depth
        self.retries = retries


        self.to_crawl = deque()
        self.urls_in_queue_set = set()
        self.domains_in_queue_set = set() 

        self.discovered_links = set()
        self.crawled_sites = {}
        self.crawled_domains = set()

        self._load_discovered_links()
        self._load_crawled_sites()
        self._load_crawled_domains() 

        initial_urls = set(seed_urls)
        for url in initial_urls:
            domain = self._get_domain(url)
            if url not in self.crawled_sites or self.crawled_sites.get(url, {}).get("status") != "crawled":
                self._add_to_crawl_queue(url, 0)
        print(f"{YELLOW}Initial to_crawl queue size: {len(self.to_crawl)}{RESET}")


    def _load_discovered_links(self):
        results = self.db_manager._execute_query(
            "SELECT url FROM discovered_onion_links", fetch_all=True
        )
        if results:
            for row in results:
                url = row['url']
                if not self.contains_nsfw(url):
                    self.discovered_links.add(url)
            print(f"{YELLOW}📂 Loaded existing discovered .onion links from DB after NSFW filtering. Total: {len(self.discovered_links)}{RESET}")
        else:
            print(f"{YELLOW}📂 No existing discovered .onion links in DB.{RESET}")

    def _load_crawled_sites(self):
        results = self.db_manager._execute_query(
            "SELECT url, last_checked, response_time, result, status FROM crawled_sites", fetch_all=True
        )
        if results:
            for row in results:
                self.crawled_sites[row['url']] = dict(row)
            print(f"{YELLOW}📂 Loaded existing crawled sites from DB. Total: {len(self.crawled_sites)}{RESET}")
        else:
            print(f"{YELLOW}📂 No existing crawled sites in DB.{RESET}")

    def _load_crawled_domains(self):
        for url in self.crawled_sites.keys():
            domain = self._get_domain(url)
            if domain:
                self.crawled_domains.add(domain)
        print(f"{YELLOW}📂 Loaded {len(self.crawled_domains)} crawled domains from DB.{RESET}")

    def save_crawled_site_status(self, url, last_checked, response_time, result, status):
        self.db_manager._execute_query(
            "INSERT OR REPLACE INTO crawled_sites (url, last_checked, response_time, result, status) VALUES (?, ?, ?, ?, ?)",
            (url, last_checked, response_time, result, status)
        )
        self.crawled_sites[url] = {
            "last_checked": last_checked,
            "response_time": response_time,
            "result": result,
            "status": status
        }
        domain = self._get_domain(url)
        if domain:
            self.crawled_domains.add(domain) #
        print(f"{GREEN}💾 Saved crawled site status for {url}{RESET}")

    def save_discovered_link(self, url):
        self.db_manager._execute_query(
            "INSERT OR IGNORE INTO discovered_onion_links (url) VALUES (?)",
            (url,)
        )
        self.discovered_links.add(url)
        print(f"{GREEN}💾 Added {url} to discovered links in DB.{RESET}")

    def _get_domain(self, url):
        try:
            return urlparse(url).netloc
        except Exception as e:
            print(f"{RED}❗ Error extracting domain from {url}: {e}{RESET}")
            return None

    def _add_to_crawl_queue(self, url, depth):
        decoded_url = unquote(url)
        domain = self._get_domain(decoded_url)

        if not domain:
            return False 

        if self.contains_nsfw(decoded_url): #
            print(f"{RED}🚫 NSFW link detected, not adding to queue: {decoded_url}{RESET}") #
            return False #

        if decoded_url in self.urls_in_queue_set: #
            print(f"{YELLOW}🔄 Already in queue: {decoded_url}{RESET}") #
            return False #
        
        if self.crawled_sites.get(decoded_url, {}).get("status") == "crawled": #
            print(f"{YELLOW}🔄 Already crawled: {decoded_url}{RESET}") #
            return False #

        if domain not in self.crawled_domains: 
            self.to_crawl.appendleft((decoded_url, depth))
            self.urls_in_queue_set.add(decoded_url)
            self.domains_in_queue_set.add(domain)
            self.save_discovered_link(decoded_url)
            print(f"{BLUE}➕ Added NEW DOMAIN URL to queue (high priority): {decoded_url} (depth: {depth}){RESET}") #
            return True #
        
        elif decoded_url not in self.discovered_links:
            self.to_crawl.append((decoded_url, depth))
            self.urls_in_queue_set.add(decoded_url)
            self.save_discovered_link(decoded_url)
            print(f"{BLUE}➕ Added unique URL from EXISTING DOMAIN to queue (low priority): {decoded_url} (depth: {depth}){RESET}") #
            return True #
        
        else:
            print(f"{YELLOW}🔄 Discovered but not in queue and not crawled: {decoded_url}. Will consider for requeue.{RESET}") #
        return False #


    def sanitize_content(self, text):
        try:
            if not isinstance(text, str):
                return ""
            text = text.lower()
            text = re.sub(r'\W+', ' ', text)
            tokens = text.split()
            try:
                stop_words = set(stopwords.words('english'))
            except LookupError:
                import nltk
                nltk.download('stopwords')
                stop_words = set(stopwords.words('english'))
            sanitized_tokens = (word for word in tokens if word not in stop_words)
            return ' '.join(sanitized_tokens)
        except Exception as e:
            print(f"{RED}❗ Error: Failed to sanitize content: {e}{RESET}")
            return ""

    def validate_url(self, url):
        decoded_url = unquote(url)
        parsed = urlparse(decoded_url)
        if not parsed.scheme or not parsed.netloc:
            return False
        return parsed.netloc.endswith('.onion')

    def exponential_backoff(self, retries):
        base_delay = 2
        max_delay = 45
        delay = min(max_delay, base_delay * math.pow(2, retries))
        return delay

    def contains_nsfw(self, text):
        if not isinstance(text, str):
            return False
        text_lower = text.lower()
        for keyword in NSFW_KEYWORDS:
            if keyword in text_lower:
                return True
        return False

    def crawl(self, url, depth, retries_left=None):
        if retries_left is None:
            retries_left = self.retries

        decoded_url = unquote(url)
        domain = self._get_domain(decoded_url)

        if decoded_url in self.urls_in_queue_set:
            self.urls_in_queue_set.remove(decoded_url)
        if domain in self.domains_in_queue_set and not any(self._get_domain(u) == domain for u, _ in self.to_crawl):
            self.domains_in_queue_set.remove(domain)

        if self.contains_nsfw(decoded_url):
            print(f"{RED}🚫 Skipping scrape: URL contains NSFW keyword - {decoded_url}{RESET}")
            self.save_crawled_site_status(decoded_url, time.ctime(), 0, "skipped_nsfw_url", "filtered")
            return set()

        if not self.validate_url(decoded_url):
            print(f"{RED}❗ Error: Invalid or skipped URL: {decoded_url}{RESET}")
            return set()

        if self.crawled_sites.get(decoded_url, {}).get("status") == "crawled":
            print(f"{YELLOW}🔄 Skipping already crawled site: {decoded_url}{RESET}")
            return set()

        start_time = time.time()
        try:
            response = self.session.get(decoded_url, timeout=75)
            elapsed_time = time.time() - start_time
            
            if response.status_code != 200:
                raise requests.exceptions.RequestException(f"Bad status code: {response.status_code}")

            soup = BeautifulSoup(response.content, 'html.parser')
            
            meta_description = soup.find('meta', attrs={'name': 'description'})
            if meta_description and 'content' in meta_description.attrs:
                content_to_save = meta_description['content']
                print(f"{CYAN}📝 Found meta description: {content_to_save[:256]}...{RESET}")
            else:
                content_to_save = soup.get_text(separator=' ')
                print(f"{YELLOW}⚠️ No meta description found for {decoded_url}. Falling back to full text.{RESET}")
            
            sanitized_content = self.sanitize_content(content_to_save[:1056])

            title = soup.title.string if soup.title else None
            date = None
            metadata = {}

            if self.contains_nsfw(title) or self.contains_nsfw(sanitized_content):
                print(f"{RED}🚫 Skipping index: Title or content contains NSFW keyword - {decoded_url}{RESET}")
                self.save_crawled_site_status(decoded_url, time.ctime(), elapsed_time, "skipped_nsfw_content", "filtered")
                return set()

            doc_id = self.link_index_manager.insert_link(decoded_url, sanitized_content, title, date, metadata)
            if doc_id:
                tokens = sanitized_content.split()
                terms_positions = defaultdict(list)
                for pos, token in enumerate(tokens):
                    terms_positions[token].append(pos)
                
                for term, positions in terms_positions.items():
                    self.reverse_index_manager.update_reverse_index(doc_id, term, positions)

            print(f"{GREEN}✅ Crawling successful: {decoded_url}{RESET}")

            self.save_crawled_site_status(decoded_url, time.ctime(), elapsed_time, "success", "crawled")
            self.crawled_domains.add(domain)

            found_links = set()
            for a_tag in soup.find_all('a', href=True):
                link = a_tag['href']
                decoded_link = unquote(link)
                if self.validate_url(decoded_link):
                    if self._add_to_crawl_queue(decoded_link, depth + 1):
                        found_links.add(decoded_link)
                    else:
                        print(f"{YELLOW}Skipping adding {decoded_link} to queue (reason logged above).{RESET}")

            for to_link in found_links:
                self.relationship_manager.add_relationship(decoded_url, to_link)

            return found_links
        except requests.exceptions.ConnectionError as e:
            elapsed_time = time.time() - start_time
            print(f"{RED}❗ Connection Error: Failed to crawl {decoded_url}: {e}{RESET}")
            self.save_crawled_site_status(decoded_url, time.ctime(), elapsed_time, str(e), "failed")
            if retries_left > 0:
                retry_delay = 5
                print(f"{YELLOW}🔄 Retrying {decoded_url} in {retry_delay:.2f} seconds ({retries_left} retries left){RESET}")
                time.sleep(retry_delay)
                return self.crawl(url, depth, retries_left=retries_left - 1)
            else:
                print(f"{RED}❗ Error: Max retries reached for {decoded_url}. Skipping to next URL.{RESET}")
                return set()
        except requests.exceptions.RequestException as e:
            elapsed_time = time.time() - start_time
            print(f"{RED}❗ Error fetching content from {decoded_url}: {e}{RESET}")
            self.save_crawled_site_status(decoded_url, time.ctime(), elapsed_time, str(e), "failed")
            if retries_left > 0:
                retry_delay = self.exponential_backoff(self.retries - retries_left)
                print(f"{YELLOW}🔄 Retrying {decoded_url} in {retry_delay:.2f} seconds ({retries_left} retries left){RESET}")
                time.sleep(retry_delay)
                return self.crawl(url, depth, retries_left=retries_left - 1)
            else:
                print(f"{RED}❗ Error: Max retries reached for {decoded_url}. Skipping to next URL.{RESET}")
                return set()
        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"{RED}❗ Critical Error during crawl of {decoded_url}: {e}{RESET}")
            self.save_crawled_site_status(decoded_url, time.ctime(), elapsed_time, str(e), "failed")
            return set()

    def run(self):
        while True:
            try:
                if not self.to_crawl:
                    print(f"{YELLOW}🔄 to_crawl queue is empty. Repopulating...{RESET}")
                    
                    self._load_discovered_links()
                    self._load_crawled_sites()
                    self._load_crawled_domains()

                    newly_discovered_uncrawled = []
                    previously_failed_or_not_crawled = []

                    for url in self.discovered_links:
                        status = self.crawled_sites.get(url, {}).get("status")
                        domain = self._get_domain(url)

                        if domain and domain not in self.crawled_domains and url not in self.urls_in_queue_set: 
                            newly_discovered_uncrawled.append((url, 0)) 
                        elif status != "crawled" and url not in self.urls_in_queue_set:
                            if url not in self.crawled_sites:
                                newly_discovered_uncrawled.append((url, 0))
                            elif status in ["failed", "not crawled", "filtered", None]:
                                previously_failed_or_not_crawled.append((url, 0))

                    random.shuffle(newly_discovered_uncrawled)
                    for url, depth in newly_discovered_uncrawled:
                        if url not in self.urls_in_queue_set:
                            self._add_to_crawl_queue(url, depth)
                            
                    random.shuffle(previously_failed_or_not_crawled)
                    for url, depth in previously_failed_or_not_crawled:
                        if url not in self.urls_in_queue_set:
                            self._add_to_crawl_queue(url, depth)

                    if not self.to_crawl:
                        print(f"{RED}❗ No more links to crawl and no new links discovered. Consider adding new seed URLs or restarting the crawler.{RESET}")
                        time.sleep(60)
                        continue
                    else:
                        print(f"{GREEN}Queue repopulated with {len(self.to_crawl)} unique URLs.{RESET}")
                
                subset_size = min(10, len(self.to_crawl))
                current_batch_urls_with_depth = random.sample(list(self.to_crawl), subset_size)

                urls_to_process_now = set(url for url, _ in current_batch_urls_with_depth)
                self.to_crawl = deque([item for item in self.to_crawl if item[0] not in urls_to_process_now])
                self.urls_in_queue_set = set(url for url, _ in self.to_crawl)
                self.domains_in_queue_set = set(self._get_domain(url) for url, _ in self.to_crawl if self._get_domain(url))

                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [executor.submit(self.crawl, url, depth) for url, depth in current_batch_urls_with_depth]
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            print(f"{RED}❗ Error in thread execution: {e}{RESET}")

                print(f"{BLUE}🌐 Crawling cycle completed. Sleeping before the next cycle... Current queue size: {len(self.to_crawl)}{RESET}")
                time.sleep(5)
            except Exception as e:
                print(f"{RED}❗ Error: LinkCrawler encountered an error: {e}{RESET}")
                time.sleep(1)

class SearchEngineCrawler(threading.Thread):
    def __init__(self, tor_session, link_index_manager, reverse_index_manager, search_engines, db_manager, query_interval=300):
        threading.Thread.__init__(self)
        self.session = tor_session.get_session()
        self.link_index_manager = link_index_manager
        self.reverse_index_manager = reverse_index_manager
        self.search_engines = search_engines
        self.db_manager = db_manager
        self.query_interval = query_interval
        self.discovered_links = set()
        self.used_terms = set()
        self._load_discovered_links()
        self._load_used_terms()

    def _load_discovered_links(self):
        """Loads discovered links from the database, filtering NSFW."""
        results = self.db_manager._execute_query(
            "SELECT url FROM discovered_onion_links", fetch_all=True
        )
        if results:
            clean_links = []
            for row in results:
                url = row['url']
                if self.contains_nsfw(url):
                    print(f"{RED}🚫 Removed NSFW link from discovered_onion_links in DB: {url}{RESET}")
                    self.db_manager._execute_query("DELETE FROM discovered_onion_links WHERE url = ?", (url,))
                else:
                    clean_links.append(url)
            self.discovered_links = set(clean_links)
            print(f"{YELLOW}📄 Loaded existing discovered .onion links from DB after NSFW filtering.{RESET}")
        else:
            print(f"{YELLOW}📄 No existing discovered .onion links in DB.{RESET}")

    def _load_used_terms(self):

        self.used_terms = set(self.reverse_index_manager.get_all_terms())
        print(f"{YELLOW}Loaded {len(self.used_terms)} terms for search.{RESET}")

    def extract_onion_links(self, text):
        """Extracts .onion links from text."""
        pattern = r'https?://[a-zA-Z0-9]{16,56}\.onion\b'
        return re.findall(pattern, text)

    def save_discovered_link(self, url):
        """Saves a discovered link to the database."""
        self.db_manager._execute_query(
            "INSERT OR IGNORE INTO discovered_onion_links (url) VALUES (?)",
            (url,)
        )
        self.discovered_links.add(url)

    def contains_nsfw(self, text):
        """Checks if the given text contains any NSFW keywords (case-insensitive)."""
        if not isinstance(text, str):
            return False
        text_lower = text.lower()
        for keyword in NSFW_KEYWORDS:
            if keyword in text_lower:
                return True
        return False

    def search_engine_query(self, search_engine_url, query, retries=3):
        """Performs a search query using the specified search engine and extracts .onion links."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0'
        }
        for attempt in range(retries):
            try:
                full_url = f"{search_engine_url}/search?q={quote(query)}"
                print(f"{BLUE}🔍 Searching on {search_engine_url} for '{query}'{RESET}")
                response = self.session.get(full_url, headers=headers, timeout=60)
                response.raise_for_status()

                onion_links = self.extract_onion_links(response.text)
                new_links_count = 0
                for link in onion_links:
                    if not self.contains_nsfw(link):
                        if link not in self.discovered_links:
                            self.save_discovered_link(link)
                            new_links_count += 1
                    else:
                        print(f"{RED}🚫 Discovered NSFW link, not saving: {link}{RESET}")
                
                print(f"{GREEN}✅ Found {len(onion_links)} links, {new_links_count} new after NSFW filter from '{query}' on {search_engine_url}{RESET}")
                return new_links_count
            except requests.exceptions.RequestException as e:
                print(f"{RED}❗ Error during search on {search_engine_url} for '{query}' (Attempt {attempt+1}/{retries}): {e}{RESET}")
                time.sleep(self.exponential_backoff(attempt))
            except Exception as e:
                print(f"{RED}❗ Unexpected error during search on {search_engine_url} for '{query}': {e}{RESET}")
                break
        return 0

    def run(self):
        while True:
            try:
                all_terms = self.reverse_index_manager.get_all_terms()
                search_terms = list(set(all_terms) - self.used_terms)

                if not search_terms:
                    print(f"{YELLOW}📄 No new search terms available. Waiting for new indexed content.{RESET}")
                    time.sleep(self.query_interval)
                    self._load_used_terms()
                    continue


                num_queries = min(5, len(search_terms))
                selected_terms = random.sample(search_terms, num_queries)

                for term in selected_terms:
                    for engine in self.search_engines:
                        self.search_engine_query(engine, term)
                        self.used_terms.add(term)
                        time.sleep(random.uniform(1, 3))

                print(f"{BLUE}📝 Search cycle completed. Sleeping for {self.query_interval} seconds.{RESET}")
                time.sleep(self.query_interval)

            except Exception as e:
                print(f"{RED}❗ Error: SearchEngineCrawler encountered an error: {e}{RESET}")
                time.sleep(self.query_interval / 10)


app = Flask(__name__)

############################

db_manager = SQLiteManager()
link_index_manager = LinkIndexManager(db_manager)
reverse_index_manager = ReverseContentIndexManager(db_manager)
relationship_manager = LinkRelationshipManager(db_manager)

SEED_URLS = [
    "http://archiveemhz42hwt3eizqf4xyb6g72b7a2d4h4t4f4o4e4i6j2d6.onion",
    "http://darkfailenbsv6y5l.onion/",
    "http://answersz7g35x2a5h6j2x7n6j5h7x7t7u5u2o2a3o6t2d6.onion",
    "http://privatekey2y6pxu3j2d6j2p6g2a4g2f4u2d4o6a2d6.onion",
    "http://pastes5b7g7e7s4l6f2a4e2g6b2n6h2v2x2m2a2d6.onion",
    "http://wiki2p52nrsbwhh5u44t4f4g2a4i2g2a4e2e2a4g2o2e6.onion",
    "http://4pt4axjgzmm4ibmxplfiuvopxzf775e5bqseyllafcecryfthdupjwyd.onion",
    "http://abacusall6l52n5gp357vpv4yjjvh6ewg65pjbfvacyqcldux66btlqd.onion",
    "http://livk2fpdv4xjnjrbxfz2tw3ptogqacn2dwfzxbxr3srinryxrcewemid.onion",
    "http://tortimeswqlzti2aqbjoieisne4ubyuoeiiugel2layyudcfrwln76qd.onion",
    "https://tor.taxi",
    "https://dark.fail",
    "http://tortaxi2dev6xjwbaydqzla77rrnth7yn2oqzjfmiuwn5h6vsk2a4syd.onion",
    "http://zjfsopfrwpvqrhiy73vxb6zq7ksyffkzfyow2gmhgvjsseogy65uguyd.onion",
    "http://s4wq4oz66bbyvsv2rg3ixwuwzvoxv226bg3563ptchx7xknelhfu3rqd.onion",
    "http://uyeygtqorgwxmp4bskauanuiofeh7frv35nvmghni5aihf32z27ogqqd.onion",
    "http://dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion",
    "http://abacuseeettcn3n2zxo7tqy5vsxhqpha2jtjqs7cgdjzl2jascr4liad.onion",
    "http://abacuskzoo7wrfmpqiqscoiljfjap42rzjkfygp5vm3gtlu5tanhbjad.onion",
    "http://h552xyfqdqblk6rqgjbesa2rpp3m6fjnsjjqayhuofrid2xibwrkbmad.onion",
    "http://pitchprash4aqilfr7sbmuwve3pnkpylqwxjbj2q5o4szcfeea6d27yd.onion",
    "http://pitchzzzoot5i4cpsblu2d5poifsyixo5r4litxkukstre5lrbjakxid.onion",
    "http://drughub666py6fgnml5kmxa7fva5noppkf6wkai4fwwvzwt4rz645aqd.onion",
    "http://drughubb7lmqymhpq24wmhihloii3dlp3xlqhz356dqdvhmkv2ngf4id.onion",
    "http://nzdnmfcf2z5pd3vwfyfy3jhwoubv6qnumdglspqhurqnuvr52khatdad.onion",
    "http://darkmat3kdxestusl437urshpsravq7oqb7t3m36u2l62vnmmldzdmid.onion",
    "http://darkmmk3owyft4zzg3j3t25ri4z5bw7klapq6q3l762kxra72sli4mid.onion",
    "http://darkmmro6j5xekpe7jje74maidkkkkw265nngjqxrv4ik7v3aiwdbtad.onion",
    "http://germania7zs27fu3gi76wlr5rd64cc2yjexyzvrbm4jufk7pibrpizad.onion",
    "http://ttq5m3lsdhjysspvof6m72lbygclzyeelvn3wgjj7m3fr4djvbgepwyd.onion",
    "http://endchancxfbnrfgauuxlztwlckytq7rgeo5v6pc2zd4nyqo3khfam4ad.onion",
    "https://www.bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion",
    "http://xssforumv3isucukbxhdhwz67hoa5e2voakcfkuieq4ch257vsburuid.onion",
    "https://www.nytimesn7cgmftshazwhfgzm37qxb44r64ytbb2dj3x62d2lljsciiyd.onion",
    "http://dumpliwoard5qsrrsroni7bdiishealhky4snigbzfmzcquwo3kml4id.onion",
    "http://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
    "http://eternalcbrzpicytj4zyguygpmkjlkddxob7tptlr25cdipe5svyqoqd.onion",
    "http://tcecdnp2fhyxlcrjoyc2eimdjosr65hweut6y7r2u6b5y75yuvbkvfyd.onion",
    "http://fairfffoxrgxgi6tkcaxhxre2hpwiuf6autt75ianjkvmcn65dxxydad.onion",
    "http://ncidetfs7banpz2d7vpndev5somwoki5vwdpfty2k7javniujekit6ad.onion",
    "http://biblemeowimkh3utujmhm6oh2oeb3ubjw2lpgeq3lahrfr2l6ev6zgyd.onion",
    "http://2gzyxa5ihm7nsggfxnu52rck2vv4rvmdlkiu3zzui5du4xyclen53wid.onion",
    "http://digdig2nugjpszzmqe5ep2bk7lqfpdlyrkojsx2j6kzalnrqtwedr3id.onion",
    "http://jqibjqqagao3peozxfs53tr6aecoyvctumfsc2xqniu4xgcrksal2iqd.onion",
    "http://lldan5gahapx5k7iafb3s4ikijc4ni7gx5iywdflkba5y2ezyg6sjgyd.onion",
    "http://shootnnngg4akh7fkjmx5b5omsppt2zaefohzwnwryhy2c6mm3kbx6qd.onion",
    "http://x4ijfwy76n6jl7rs4qyhe6qi5rv6xyuos3kaczgjpjcajigjzk3k7wqd.onion",
    "http://featherdvtpi7ckdbkb2yxjfwx3oyvr3xjz3oo4rszylfzjdg6pbm3id.onion",
    "http://volkancfgpi4c7ghph6id2t7vcntenuly66qjt6oedwtjmyj4tkk5oqd.onion",
    "http://archiveiya74codqgiixo33q62qlrqtkgmcitqx5u2oeqnmn5bpcbiyd.onion",
    "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion",
    "http://www.dds6qkxpwdeubwucdiaord2xgbbeyds25rbsgr73tbfpqpt4a6vjwsyd.onion",
    "http://hszyoqwrcp7cxlxnqmovp6vjvmnwj33g4wviuxqzq47emieaxjaperyd.onion",
    "http://njallalafimoej5i4eg7vlnqjvmb6zhdh27qxcatdn647jtwwwui3nad.onion",
    "http://rurcblzhmdk22kttfkel2zduhyu3r6to7knyc7wiorzrx5gw4c3lftad.onion",
    "http://www.qubesosfasa4zl44o4tws22di6kepyzfeqv3tg4e3ztknltfxqrymdad.onion",
    "http://xdkriz6cn2avvcr2vks5lvvtmfojz2ohjzj4fhyuka55mvljeso2ztqd.onion",
    "http://tp7mtouwvggdlm73vimqkuq7727a4ebrv4vf4cnk6lfg4fatxa6p2ryd.onion",
    "http://o54hon2e2vj6c7m3aqqu6uyece65by3vgoxxhlqlsvkmacw6a7m7kiad.onion",
    "http://danielas3rtn54uwmofdo3x2bsdifr47huasnmbgqzfrec5ubupvtpid.onion",
    "http://stormwayszuh4juycoy4kwoww5gvcu2c4tdtpkup667pdwe4qenzwayd.onion",
    "http://vww6ybal4bd7szmgncyruucpgfkqahzddi37ktceo3ah7ngmcopnpyyd.onion",
    "http://keybase5wmilwokqirssclfnsqrjdsi7jdir5wy7y7iu3tanwmtp6oid.onion",
    "http://5gdvpfoh6kb2iqbizb37lzk2ddzrwa47m6rpdueg2m656fovmbhoptqd.onion",
    "http://xxtbwyb5z5bdvy2f6l2yquu5qilgkjeewno4qfknvb3lkg3nmoklitid.onion",
    "http://pissmaiamldg5ciulncthgzudvh5d55dismyqf6qdkx372n2b5osefid.onion",
    "http://monerotoruzizulg5ttgat2emf4d6fbmiea25detrmmy7erypseyteyd.onion",
    "http://6n5nbusxgyw46juqo3nt5v4zuivdbc7mzm74wlhg7arggetaui4yp4id.onion",
    "http://blkchairbknpn73cfjhevhla7rkp4ed5gg2knctvv7it4lioy22defid.onion",
    "http://protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion",
    "http://6voaf7iamjpufgwoulypzwwecsm2nu7j5jpgadav2rfqixmpl4d65kid.onion",
    "http://g66ol3eb5ujdckzqqfmjsbpdjufmjd5nsgdipvxmsh7rckzlhywlzlqd.onion/d/TorDotTaxi",
    "http://s4k4ceiapwwgcm3mkb6e4diqecpo7kvdnfr5gg7sph7jjppqkvwwqtyd.onion/",
    "http://6nhmgdpnyoljh5uzr5kwlatx2u3diou4ldeommfxjz3wkhalzgjqxzqd.onion/",
    "http://2jwcnprqbugvyi6ok2h2h7u26qc6j5wxm7feh3znlh2qu3h6hjld4kyd.onion/",
    "http://jgwe5cjqdbyvudjqskaajbfibfewew4pndx52dye7ug3mt3jimmktkid.onion/",
    "http://prjd5pmbug2cnfs67s3y65ods27vamswdaw2lnwf45ys3pjl55h2gwqd.onion/",
    "http://55niksbd22qqaedkw36qw4cpofmbxdtbwonxam7ov2ga62zqbhgty3yd.onion/",
    "http://s57divisqlcjtsyutxjz2ww77vlbwpxgodtijcsrgsuts4js5hnxkhqd.onion/",
    "http://wbz2lrxhw4dd7h5t2wnoczmcz5snjpym4pr7dzjmah4vi6yywn37bdyd.onion/",
    "http://iwggpyxn6qv3b2twpwtyhi2sfvgnby2albbcotcysd5f7obrlwbdbkyd.onion/",
    "http://rfyb5tlhiqtiavwhikdlvb3fumxgqwtg2naanxtiqibidqlox5vispqd.onion/",
    "http://ajlu6mrc7lwulwakojrgvvtarotvkvxqosb4psxljgobjhureve4kdqd.onion/",
    "http://y22arit74fqnnc2pbieq3wqqvkfub6gnlegx3cl6thclos4f7ya7rvad.onion/",
    "http://ovai7wvp4yj6jl3wbzihypbq657vpape7lggrlah4pl34utwjrpetwid.onion/",
    "http://hqfld5smkr4b4xrjcco7zotvoqhuuoehjdvoin755iytmpk4sm7cbwad.onion/",
    "http://jbtb75gqlr57qurikzy2bxxjftzkmanynesmoxbzzcp7qf5t46u7ekqd.onion/",
    "http://jhi4v5rjly75ggha26cu2eeyfhwvgbde4w6d75vepwxt2zht5sqfhuqd.onion/",
    "http://rxmyl3izgquew65nicavsk6loyyblztng6puq42firpvbe32sefvnbad.onion/",
    "http://vhlehwexxmbnvecbmsk4ormttdvhlhbnyabai4cithvizzaduf3gmayd.onion/",
    "http://guzjgkpodzshso2nohspxijzk5jgoaxzqioa7vzy6qdmwpz3hq4mwfid.onion/",
    "http://n6qisfgjauj365pxccpr5vizmtb5iavqaug7m7e4ewkxuygk5iim6yyd.onion/",
    "http://uescqfrcztbhb6tmhdlbejrjfwgtpckcoiwmwq5bfq5hhkwfioan7qad.onion/",
    "http://kl4gp72mdxp3uelicjjslqnpomqfr5cbdd3wzo5klo3rjlqjtzhaymqd.onion/",
    "http://ymvhtqya23wqpez63gyc3ke4svju3mqsby2awnhd3bk2e65izt7baqad.onion/",
    "http://k6m3fagp4w4wspmdt23fldnwrmknse74gmxosswvaxf3ciasficpenad.onion/",
    "http://7mejofwihleuugda5kfnr7tupvfbaqntjqnfxc4hwmozlcmj2cey3hqd.onion/",
    "http://lqcjo7esbfog5t4r44gyy7jurpzf6cavpfmc4vkal4k2g4ie66ao5mryd.onion/",
    "http://qazkxav4zzmt5xwfw6my362jdwhzrcafz7qpd5kugfgx7z7il5lyb6ad.onion/",
    "http://p2qzxkca42e3wccvqgby7jrcbzlf6g7pnkvybnau4szl5ykdydzmvbid.onion/",
    "http://gd5x24pjoan2pddc2fs6jlmnqbawq562d2qyk6ym4peu5ihzy6gd4jad.onion/",
    "http://2ln3x7ru6psileh7il7jot2ufhol4o7nd54z663xonnnmmku4dgkx3ad.onion/",
    "http://usmost4cbpesx552s2s4ti3c4nk2xgiu763vhcs3b4uc4ppp3zwnscyd.onion/",
    "http://mp3fpv6xbrwka4skqliiifoizghfbjy5uyu77wwnfruwub5s4hly2oid.onion/",
    "http://t43fsf65omvf7grt46wlt2eo5jbj3hafyvbdb7jtr2biyre5v24pebad.onion/",
    "http://okayd5ljzdv4gzrtiqlhtzjbflymfny2bxc2eacej3tamu2nyka7bxad.onion/",
    "http://xf2gry25d3tyxkiu2xlvczd3q7jl6yyhtpodevjugnxia2u665asozad.onion/",
    "http://3bp7szl6ehbrnitmbyxzvcm3ieu7ba2kys64oecf4g2b65mcgbafzgqd.onion/",
    "http://xykxv6fmblogxgmzjm5wt6akdhm4wewiarjzcngev4tupgjlyugmc7qd.onion/",
    "http://sga5n7zx6qjty7uwvkxpwstyoh73shst6mx3okouv53uks7ks47msayd.onion/",
    "http://kq4okz5kf4xosbsnvdr45uukjhbm4oameb6k6agjjsydycvflcewl4qd.onion/",
    "http://wk3mtlvp2ej64nuytqm3mjrm6gpulix623abum6ewp64444oreysz7qd.onion/",
    "http://odahix2ysdtqp4lgak4h2rsnd35dmkdx3ndzjbdhk3jiviqkljfjmnqd.onion/",
    "http://45tbhx5prlejzjgn36nqaxqb6qnm73pbohuvqkpxz2zowh57bxqawkid.onion/",
    "https://kcmykvkkt3umiyx4xouu3sjo6odz3rolqphy2i2bbdan33g3zrjfjgqd.onion/",
    "http://zgeajoabenj2nac6k5cei5qy62iu5yun5gm2vjnxy65r3p3amzykwxqd.onion/",
    "http://ozmh2zkwx5cjuzopui64csb5ertcooi5vya6c2gm4e3vcvf2c2qvjiyd.onion/",
    "http://cathug2kyi4ilneggumrenayhuhsvrgn6qv2y47bgeet42iivkpynqad.onion/",
    "http://sik5nlgfc5qylnnsr57qrbm64zbdx6t4lreyhpon3ychmxmiem7tioad.onion/",
    "http://dhosting4xxoydyaivckq7tsmtgi4wfs3flpeyitekkmqwu4v4r46syd.onion/",
    "http://nanochanqzaytwlydykbg5nxkgyjxk3zsrctxuoxdmbx5jbh2ydyprid.onion/",
    "http://picochanwvqfa2xsrfzlul4x4aqtog2eljll5qnj5iagpbhx2vmfqnid.onion/",
    "http://enxx3byspwsdo446jujc52ucy2pf5urdbhqw3kbsfhlfjwmbpj5smdad.onion/",
    "http://dngtk6iydmpokbyyk3irqznceft3hze6q6rasrqlz46v7pq4klxnl4yd.onion/",
    "http://cct5wy6mzgmft24xzw6zeaf55aaqmo6324gjlsghdhbiw5gdaaf4pkad.onion/",
    "http://wnrgozz3bmm33em4aln3lrbewf3ikxj7fwglqgla2tpdji4znjp7viqd.onion/",
    "http://7sk2kov2xwx6cbc32phynrifegg6pklmzs7luwcggtzrnlsolxxuyfyd.onion/",
    "http://eludemailxhnqzfmxehy3bk5guyhlxbunfyhkcksv4gvx6d3wcf6smad.onion/",
    "http://lainwir3s4y5r7mqm3kurzpljyf77vty2hrrfkps6wm4nnnqzest4lqd.onion/",
    "http://cgjzkysxa4ru5rhrtr6rafckhexbisbtxwg2fg743cjumioysmirhdad.onion/",
    "http://killnod2s77o3axkktdu52aqmmy4acisz2gicbhjm4xbvxa2zfftteyd.onion/",
    "http://digdeep4orxw6psc33yxa2dgmuycj74zi6334xhxjlgppw6odvkzkiad.onion/",
    "http://spywaredrcdg5krvjnukp3vbdwiqcv3zwbrcg6qh27kiwecm4qyfphid.onion/",
    "http://meynethaffeecapsvfphrcnfrx44w2nskgls2juwitibvqctk2plvhqd.onion/",
    "http://zsxjtsgzborzdllyp64c6pwnjz5eic76bsksbxzqefzogwcydnkjy3yd.onion/",
    "http://g7ejphhubv5idbbu3hb3wawrs5adw7tkx7yjabnf65xtzztgg4hcsqqd.onion/",
    "http://ciadotgov4sjwlzihbbgxnqg3xiyrg7so2r2o3lt5wz5ypk4sxyjstad.onion/",
    "http://archivebyd3rzt3ehjpm4c3bjkyxv3hjleiytnvxcn7x32psn2kxcuid.onion/",
    "http://bible4u2lvhacg4b3to2e2veqpwmrc2c3tjf2wuuqiz332vlwmr4xbad.onion/",
    "http://kx5thpx2olielkihfyo4jgjqfb7zx7wxr3sd4xzt26ochei4m6f7tayd.onion/",
    "http://nv3x2jozywh63fkohn5mwp2d73vasusjixn3im3ueof52fmbjsigw6ad.onion/",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/Contest2022",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/The_Matrix",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/How_to_Exit_the_Matrix",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/Verifying_PGP_signatures",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/In_Praise_Of_Hawala",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/Terrific_Strategies_To_Apply_A_Social_media_Marketing_Approach",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/SnapBBSIndex",
    "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/wiki/Onionland%27s_Museum",
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/",
    "http://torlinksge6enmcyyuxjpjkoouw4oorgdgeo7ftnq3zodj7g2zxi3kyd.onion/",
    "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion/",
    "http://jaz45aabn5vkemy4jkg4mi4syheisqn2wn2n4fsuitpccdackjwxplad.onion/",
    "http://zqktlwi4fecvo6ri.onion/wiki/index.php/Main_Page",
    "http://vw5vzi62xqhihghvonatid7imut2rkgiudl3xomj4jftlmanuwh4r2qd.onion/",
    "http://56dlutemceny6ncaxolpn6lety2cqfz5fd64nx4ohevj4a7ricixwzad.onion/",
    "http://hbl6udan73w7qbjdey6chsu5gq5ehrfqbb73jq726kj3khnev2yarlid.onion/",
    "http://netauthlixnkiat36qeh25w5t6ljyqwug3me6nprebo4s74lzvm3p3id.onion/",
    "http://financo6ytrzaoqg.onion/",
    "http://d46a7ehxj6d6f2cf4hi3b424uzywno24c7qtnvdvwsah5qpogewoeqid.onion/",
    "http://hssza6r6fbui4x452ayv3dkeynvjlkzllezxf3aizxppmcfmz2mg7uad.onion/",
    "http://n3irlpzwkcmfochhuswpcrg35z7bzqtaoffqecomrx57n3rd5jc72byd.onion/"
    ]
    # Search engines for discovering new .onion links
SEARCH_ENGINES = [
    "http://6pxxjp7l2fervwwxiwr7kkheoed2gch6c2kkpionsjckk2molias2cad.onion/search.php?q=SEARCH_TERM",
    "http://wbr4bzzxbeidc6dwcqgwr3b6jl7ewtykooddsc5ztev3t3otnl45khyd.onion/evo/?thumbs=on&q=SEARCH_TERM",
    "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q=SEARCH_TERM",
    "http://matesea7myfqb62sbjtpx3dfchalnpf2b4ppw52lzuxwvlbtj2kb3nqd.onion/?s=SEARCH_TERM",
    "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q=SEARCH_TERM"
    ]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    results_per_page = 10

    search_results = []
    total_results = 0

    if query:
        query_terms = query.split()

        docs_for_all_terms = defaultdict(lambda: {'score': 0, 'positions': []})

        if query_terms:
            first_term_docs = reverse_index_manager.get_docs_for_term(query_terms[0])
            for doc_id, positions in first_term_docs.items():
                docs_for_all_terms[doc_id]['score'] += len(positions) # Basic scoring
                docs_for_all_terms[doc_id]['positions'].extend(positions)

            for i in range(1, len(query_terms)):
                term = query_terms[i]
                current_term_docs = reverse_index_manager.get_docs_for_term(term)
                
                common_doc_ids = set(docs_for_all_terms.keys()) & set(current_term_docs.keys())
                
                docs_for_all_terms_temp = defaultdict(lambda: {'score': 0, 'positions': []})
                for doc_id in common_doc_ids:
                    docs_for_all_terms_temp[doc_id]['score'] = docs_for_all_terms[doc_id]['score'] + len(current_term_docs[doc_id])
                    docs_for_all_terms_temp[doc_id]['positions'].extend(docs_for_all_terms[doc_id]['positions'])
                    docs_for_all_terms_temp[doc_id]['positions'].extend(current_term_docs[doc_id])
                docs_for_all_terms = docs_for_all_terms_temp

        sorted_doc_ids = sorted(docs_for_all_terms.keys(), key=lambda doc_id: docs_for_all_terms[doc_id]['score'], reverse=True)

        for doc_id in sorted_doc_ids:
            link_data = link_index_manager.get_link_by_id(doc_id)
            if link_data:
                search_results.append(link_data)
        total_results = len(search_results)

    total_pages = ceil(total_results / results_per_page) if total_results > 0 else 1
    page = max(1, min(page, total_pages))
    start_index = (page - 1) * results_per_page
    end_index = start_index + results_per_page
    results_to_display = search_results[start_index:end_index]

    return render_template('search.html',
                           query=query,
                           results=results_to_display,
                           page=page,
                           total_pages=total_pages,
                           total_results=total_results,
                           min=min,
                           max=max)

@app.route('/crawled_sites')
def crawled_sites():
    page = int(request.args.get('page', 1))
    sites_per_page = 25

    all_crawled_sites_data = db_manager._execute_query(
        "SELECT url, last_checked, response_time, result, status FROM crawled_sites ORDER BY last_checked DESC",
        fetch_all=True
    )
    all_crawled_sites = [dict(site) for site in all_crawled_sites_data] if all_crawled_sites_data else []

    total_sites = len(all_crawled_sites)
    total_pages = ceil(total_sites / sites_per_page) if total_sites > 0 else 1

    page = max(1, min(page, total_pages))

    start_index = (page - 1) * sites_per_page
    end_index = start_index + sites_per_page
    sites_to_display = all_crawled_sites[start_index:end_index]

    return render_template('crawled_sites.html',
                           crawled_sites=sites_to_display,
                           page=page,
                           total_pages=total_pages,
                           total_sites=total_sites,
                           min=min,
                           max=max)

@app.route('/indexed_links')
def indexed_links():
    page = int(request.args.get('page', 1))
    links_per_page = 25

    indexed_data = link_index_manager.get_all_links()
    all_indexed_links = indexed_data if indexed_data else []

    total_links = len(all_indexed_links)
    total_pages = ceil(total_links / links_per_page) if total_links > 0 else 1

    page = max(1, min(page, total_pages))

    start_index = (page - 1) * links_per_page
    end_index = start_index + links_per_page
    links_to_display = all_indexed_links[start_index:end_index]

    return render_template('indexed_links.html',
                           indexed_links=links_to_display,
                           page=page,
                           total_pages=total_pages,
                           total_links=total_links,
                           min=min,
                           max=max)


if __name__ == '__main__':
    TOR_PROXIES = [
        {"port": 9021, "proxy_port": 9020},
        {"port": 9031, "proxy_port": 9030},
        {"port": 9041, "proxy_port": 9040},
        {"port": 9051, "proxy_port": 9050},
        {"port": 9061, "proxy_port": 9060},
        {"port": 9071, "proxy_port": 9070},
        {"port": 9081, "proxy_port": 9080},
        {"port": 9091, "proxy_port": 9090},
        {"port": 9011, "proxy_port": 9010},
    ]

    tor_sessions = []
    crawler_threads = []
    search_engine_threads = []

    for i, config in enumerate(TOR_PROXIES):
        print(f"{CYAN}Initializing TorSession {i+1}/{len(TOR_PROXIES)} for port {config['port']} and proxy port {config['proxy_port']}{RESET}")
        tor_session = TorSession(port=config['port'], proxy_port=config['proxy_port'])
        tor_sessions.append(tor_session)
        tor_session.connect() 

    for i, tor_session in enumerate(tor_sessions):
        crawler = LinkCrawler(
            tor_session=tor_session,
            link_index_manager=link_index_manager,
            reverse_index_manager=reverse_index_manager,
            relationship_manager=relationship_manager,
            seed_urls=SEED_URLS,
            db_manager=db_manager,
            depth=2,
            retries=1
        )
        crawler.daemon = True
        crawler_threads.append(crawler)
        crawler.start()
        print(f"{GREEN}Started LinkCrawler thread {i+1} using TorSession on port {tor_session.port}{RESET}")

    for i, tor_session in enumerate(tor_sessions):
        search_crawler = SearchEngineCrawler(
            tor_session=tor_session,
            link_index_manager=link_index_manager,
            reverse_index_manager=reverse_index_manager,
            search_engines=SEARCH_ENGINES,
            db_manager=db_manager,
            query_interval=300
        )
        search_crawler.daemon = True
        search_engine_threads.append(search_crawler)
        search_crawler.start()
        print(f"{GREEN}Started SearchEngineCrawler thread {i+1} using TorSession on port {tor_session.port}{RESET}")

    try:
        print(f"{GREEN}Starting Flask web server...{RESET}")
        app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print(f"{YELLOW}Shutting down application.{RESET}")
    finally:
        for tor_session in tor_sessions:
            tor_session.close_controller()
        db_manager.close()
        print(f"{YELLOW}Application shutdown complete.{RESET}")
