![BlackEye Search Logo](blackeye.png)

# BlackEye Search: Tor-Enabled Web Crawler and Search Engine

BlackEye Search is a Python-based project designed to crawl and index `.onion` websites using multiple Tor connections, providing a searchable interface via a Flask web application. It includes features for content indexing, link relationship tracking, and basic NSFW filtering.

**Disclaimer**: This tool is for educational and research purposes only. Crawling the Tor network can be resource-intensive and may expose you to various types of content. Please ensure you understand and comply with all applicable laws and ethical guidelines when using this tool.

## 🚀 Features

* **Multi-Instance Tor Crawling**: Utilizes multiple independent Tor connections to enhance crawling speed and resilience.
* **Deep Web Indexing**: Indexes content from `.onion` sites into an SQLite database.
* **Search Engine**: Provides a Flask web interface for searching indexed `.onion` sites based on keywords.
* **NSFW Filtering**: Basic keyword-based filtering for URLs, titles, and content to help mitigate exposure to unwanted material.
* **Link Relationship Tracking**: Stores relationships between crawled URLs.
* **Crawled Site Status**: Tracks the status (success, failed, skipped) of crawled sites.
* **Persistent Storage**: Uses SQLite for all indexed data, ensuring data persists across restarts.
* **Command-Line Interface**: Provides logging and status updates in the terminal.

## ⚙️ Prerequisites

Before running BlackEye Search, ensure you have the following installed:

* **Python 3.x**: The project is developed with Python 3.
* **Tor**: The Tor daemon must be installed and accessible on your system. You will need multiple Tor instances running on different ports for the multi-connection feature.
* **pip**: Python package installer (usually comes with Python).

## 📦 Installation

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/DeadCatx3/blackeye.git
    cd BlackEye-Search
    ```

2.  **Install Python Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    This will install: `aiohttp`, `requests`, `beautifulsoup4`, `colorama`, `nltk`, `stem`, and `Flask`.

3.  **Set up Multiple Tor Instances**:
    The project is configured to work with 5 separate Tor instances. You can use the provided `run_multiple_tors.sh` script to set this up.

    * **Make the script executable**:
        ```bash
        chmod +x run_multiple_tors.sh
        ```
    * **Run the Tor setup script**:
        ```bash
        ./run_multiple_tors.sh
        ```
        This script will create a `tor_instances` directory, generate `torrc` files, and start each Tor instance in the background on the following ports:
        * **Instance 1**: ControlPort `9051`, SocksPort `9050`
        * **Instance 2**: ControlPort `9061`, SocksPort `9060`
        * **Instance 3**: ControlPort `9071`, SocksPort `9070`
        * **Instance 4**: ControlPort `9081`, SocksPort `9080`
        * **Instance 5**: ControlPort `9091`, SocksPort `9090`

    **Note**: Ensure that these ports are not already in use on your system. If they are, you will need to adjust the `TOR_CONFIGS` array in `run_multiple_tors.sh` and corresponding `TOR_PROXIES` in `tor_crawl.py`.

## 🚀 Usage

1.  **Start the Tor instances**:
    If you haven't already, run the `run_multiple_tors.sh` script:
    ```bash
    ./run_multiple_tors.sh
    ```
    This will start the Tor processes in the background.

2.  **Run the BlackEye Search application**:
    ```bash
    python tor_crawl.py
    ```
    This will start the Flask web server and initiate the crawling and search engine threads.

3.  **Access the Web Interface**:
    Open your web browser and navigate to `http://127.0.0.1:80` (or `http://localhost:80`).

    You can access the following pages:
    * `/`: The main search page.
    * `/search?q=your_query`: Search results page.
    * `/crawled_sites`: Lists all sites that have been attempted to be crawled, along with their status.
    * `/indexed_links`: Lists all links that have been successfully indexed.

## ⚙️ Configuration

You can modify the following in `tor_crawl.py`:

* **`SEED_URLS`**: A list of `.onion` URLs to start the crawling process from.
* **`SEARCH_ENGINES`**: A list of `.onion` search engine URLs that the `SearchEngineCrawler` will query.
* **`TOR_PROXIES`**: The list of control and SOCKS ports for your Tor instances. This must match the setup in `run_multiple_tors.sh`.
* **`NSFW_KEYWORDS`**: Expand or modify this list to enhance or customize content filtering.

## 🤝 Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue.

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).