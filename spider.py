import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import json
from urllib.parse import urlparse

user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'

def format_url(href, base_url):
    if href.startswith('http'):
        return href
    elif href.startswith('/'):
        return base_url + href
    elif href.startswith('#') or href.startswith('javascript:'):
        return None
    else:
        return base_url + '/' + href

def is_same_domain(url, domain):
    parsed_url = urlparse(url)
    return parsed_url.netloc == domain

def load_exclusion_patterns(filename, full_url_required):
    try:
        with open(filename, 'r') as file:
            patterns = [line.strip() for line in file if line.strip()]
            if full_url_required:
                patterns = [pattern.replace('...', '') for pattern in patterns if '...' in pattern]
            return patterns
    except FileNotFoundError:
        print(f"File not found: {filename}")
        return None

def is_excluded(url, exclusion_patterns):
    return any(pattern in url for pattern in exclusion_patterns)

def create_db():
    conn = sqlite3.connect('spider.sqlite')
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS Pages
    (id INTEGER PRIMARY KEY, url TEXT UNIQUE, html TEXT, error INTEGER, old_rank REAL, new_rank REAL, access TEXT, attempt_count INTEGER DEFAULT 0)''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS Links (from_id INTEGER, to_id INTEGER)''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS Webs (url TEXT UNIQUE)''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS Errors
    (id INTEGER, url TEXT, error_code INTEGER, error_message TEXT,
     FOREIGN KEY(id) REFERENCES Pages(id))''')
    conn.commit()
    conn.close()

def load_settings():
    try:
        with open('settings.json', 'r') as file:
            settings = json.load(file)
        return settings
    except FileNotFoundError:
        return {}

def save_settings(settings):
    with open('settings.json', 'w') as file:
        json.dump(settings, file, indent=4)

def get_valid_exclusion_file(prompt):
    while True:
        filename = input(prompt)
        if load_exclusion_patterns(filename, True) is not None:
            return filename
        print("Invalid file. Please enter a valid filename.")

def update_settings(settings):
    print("Updating settings...")
    save_settings(settings)
    print("Settings saved.")

def main():
    settings = load_settings()
    if settings:
        print("Loaded settings from settings.json")
        use_same_url = input(f"Use the same URL as before ({settings['base_url']})? (1=Yes, 0=No): ")
        if use_same_url == '1':
            base_url = settings['base_url']
        else:
            base_url = input('Enter new base URL to Crawl: ')
            settings['base_url'] = base_url
            update_settings(settings)
        
        domain = urlparse(base_url).netloc
        stay_within_domain = settings["stay_within_domain"]
        use_exclusion = settings["use_exclusion"]
        if use_exclusion:
            update_exclusion = input("Update exclusion patterns from file (1=Yes, 0=No)? ")
            if update_exclusion == '1':
                exclusion_file = settings.get("exclusion_file", "")
                exclusion_file = get_valid_exclusion_file(f"Enter filename with exclusion patterns (previous: {exclusion_file}): ")
                exclusion_patterns = load_exclusion_patterns(exclusion_file, not stay_within_domain)
                settings["exclusion_patterns"] = exclusion_patterns
                settings["exclusion_file"] = exclusion_file
                update_settings(settings)
            else:
                exclusion_patterns = settings["exclusion_patterns"]
        else:
            exclusion_patterns = []
        parse_excluded = settings["parse_excluded"]
    else:
        base_url = input('Enter base URL to Crawl: ')
        domain = urlparse(base_url).netloc
        stay_within_domain = bool(int(input('Stay within the domain (1=Yes, 0=No)? ')))
        use_exclusion = bool(int(input('Use exclusion patterns (1=Yes, 0=No)? ')))
        exclusion_patterns = []
        exclusion_file = ""
        if use_exclusion:
            exclusion_file = get_valid_exclusion_file('Enter filename with exclusion patterns: ')
            exclusion_patterns = load_exclusion_patterns(exclusion_file, not stay_within_domain)
        parse_excluded = bool(int(input('Parse links on excluded pages (1=Yes, 0=No)? ')))
        settings = {
            "base_url": base_url,
            "stay_within_domain": stay_within_domain,
            "use_exclusion": use_exclusion,
            "exclusion_file": exclusion_file,
            "exclusion_patterns": exclusion_patterns,
            "parse_excluded": parse_excluded
        }
        save_settings(settings)

    create_db()
    conn = sqlite3.connect('spider.sqlite')
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO Pages (url, access) VALUES (?, ?)', (base_url, ''))
    conn.commit()

    while True:
        cur.execute('SELECT id, url, attempt_count FROM Pages WHERE html IS NULL AND error IS NULL AND (access IS NULL OR access != "access denied") LIMIT 1')
        row = cur.fetchone()
        if row is None:
            print('No unretrieved HTML pages found')
            break

        from_id, url, attempts = row
        print('Retrieving:', url)
        try:
            if is_excluded(url, exclusion_patterns):
                print(f'Skipping excluded URL: {url}')
                if not parse_excluded:
                    cur.execute('UPDATE Pages SET access="excluded" WHERE url=?', (url,))
                    conn.commit()
                    continue

            headers = {'User-Agent': user_agent}
            response = requests.get(url, headers=headers)
            time.sleep(1)  # Sleep for 1 second between requests
            if response.status_code != 200:
                print('Error on page:', response.status_code)
                cur.execute('INSERT INTO Errors (id, url, error_code, error_message) VALUES (?, ?, ?, ?)',
                            (from_id, url, response.status_code, response.reason))
                attempts += 1
                if attempts >= 3:
                    cur.execute('UPDATE Pages SET access="access denied" WHERE url=?', (url,))
                else:
                    cur.execute('UPDATE Pages SET attempt_count=?, error=? WHERE url=?', (attempts, response.status_code, url))
            else:
                html = response.text
                if not is_excluded(url, exclusion_patterns):
                    cur.execute('UPDATE Pages SET html=?, access="granted" WHERE url=?', (html, url))
                soup = BeautifulSoup(html, 'html.parser')
                tags = soup('a')
                count = 0
                for tag in tags:
                    href = tag.get('href', None)
                    if href:
                        formatted_href = format_url(href, base_url)
                        if formatted_href and (not stay_within_domain or is_same_domain(formatted_href, domain)):
                            if not is_excluded(formatted_href, exclusion_patterns):
                                cur.execute('INSERT OR IGNORE INTO Pages (url) VALUES (?)', (formatted_href,))
                                count += 1
                                cur.execute('SELECT id FROM Pages WHERE url=? LIMIT 1', (formatted_href,))
                                to_id = cur.fetchone()
                                if to_id:
                                    cur.execute('INSERT INTO Links (from_id, to_id) VALUES (?, ?)', (from_id, to_id[0]))
                print(count, 'new links found')
            conn.commit()
        except Exception as e:
            print('Failed to retrieve or parse page:', e)
            attempts += 1
            if attempts >= 3:
                cur.execute('UPDATE Pages SET access="access denied" WHERE url=?', (url,))
            else:
                cur.execute('UPDATE Pages SET attempt_count=? WHERE url=?', (attempts, url))
            conn.commit()
    conn.close()

if __name__ == '__main__':
    main()
