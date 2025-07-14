# ~/Apps/sclik/app/main.py (updated)
import subprocess
import sqlite3
import os
import json
import time
import argparse
import tempfile
import sys
import itertools

from ipfs_setup_handler import IpfsSetupHandler

# Configuration
HOME_DIR = os.path.expanduser("~/.sclik")
DB_PATH = os.path.join(HOME_DIR, "sclik.db")
PROFILE_DIR = os.path.join(HOME_DIR, "profiles")
CONFIG_PATH = os.path.join(HOME_DIR, "config.json")

# Colors
WHITE = '\033[97m'
GREEN = '\033[92m'
BLUE = '\033[94m'
RESET = '\033[0m'

# ASCII art to display on startup
ASCII_ART = r"""       _____ ________    ______ __
      / ___// ____/ /   /  _/ //_/
      \__ \/ /   / /    / // ,<   
     ___/ / /___/ /____/ // /| |  
    /____/\____/_____/___/_/ |_| 

============================================================================== 
"""

# Initialize local storage
def init():
    os.makedirs(HOME_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, user TEXT, content TEXT, timestamp REAL, ipfs_hash TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS follows (username TEXT PRIMARY KEY, ipns_key TEXT)''')
    conn.commit()
    conn.close()

# Get or set own username
def get_own_username():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
            if 'username' in config:
                return config['username']
    
    username = input("No username set. Please enter your username: ").strip()
    while not username:
        username = input("Username cannot be empty. Please enter your username: ").strip()
    
    with open(CONFIG_PATH, 'w') as f:
        json.dump({'username': username}, f, indent=4)
    
    return username

# Update user profile with post hash and publish to IPNS
def update_profile(username, post_hash):
    profile_path = os.path.join(PROFILE_DIR, f"{username}.json")
    profile = {"username": username, "posts": []}
    
    # Load existing profile
    if os.path.exists(profile_path):
        with open(profile_path, 'r') as f:
            profile = json.load(f)
    
    # Add new post hash
    if post_hash and post_hash not in profile["posts"]:
        profile["posts"].append(post_hash)
    
    # Save profile locally
    with open(profile_path, 'w') as f:
        json.dump(profile, f, indent=4)
    
    # Publish to IPFS and IPNS
    ipfs_hash = None
    ipns_key = None
    ipfs_handler = IpfsSetupHandler()
    ipfs_handler.ensure_running()
    try:
        # Check and generate IPNS key for username if needed
        keys = subprocess.run(['ipfs', 'key', 'list'], capture_output=True, text=True, check=True).stdout.splitlines()
        if username not in keys:
            subprocess.run(['ipfs', 'key', 'gen', '--type=ed25519', username], check=True)
        
        # Get IPNS key CID
        key_lines = subprocess.run(['ipfs', 'key', 'list', '-l'], capture_output=True, text=True, check=True).stdout.splitlines()
        for line in key_lines:
            parts = line.split()
            if len(parts) == 2 and parts[1] == username:
                ipns_key = parts[0]
                break
        
        if ipns_key:
            print(f"Share this IPNS key with followers: {ipns_key}")
        
        # Add profile to IPFS
        result = subprocess.run(['ipfs', 'add', '-q', profile_path], capture_output=True, text=True, check=True)
        ipfs_hash = result.stdout.strip()
        
        # Publish to IPNS with animation
        if ipns_key:
            cmd = ['ipfs', 'name', 'publish', '--key=' + username, '/ipfs/' + ipfs_hash]
            print("Publishing to IPNS... ", end='', flush=True)
            spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            while process.poll() is None:
                sys.stdout.write(next(spinner))
                sys.stdout.flush()
                time.sleep(0.2)
                sys.stdout.write('\b')
            stdout, stderr = process.communicate()
            print()  # Newline after spinner
            if process.returncode != 0:
                print(f"Failed to publish to IPNS: {stderr.strip()}")
                raise subprocess.CalledProcessError(process.returncode, cmd, stdout, stderr)
            else:
                print(stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"Failed to update profile on IPFS/IPNS: {e}")
    
    # Store profile hash in config
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
    else:
        config = {'username': username}
    config['profile_hash'] = ipfs_hash
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    
    return ipfs_hash

# Post a message
def post(content):
    username = get_own_username()
    # Create post
    post_data = {"user": username, "content": content, "timestamp": time.time()}
    ipfs_hash = None
    
    # Try publishing to IPFS
    ipfs_handler = IpfsSetupHandler()
    ipfs_handler.ensure_running()
    try:
        # Write post to a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(post_data, tmp, indent=4)
            tmp_path = tmp.name
        
        # Run ipfs add
        result = subprocess.run(['ipfs', 'add', '-q', tmp_path], capture_output=True, text=True, check=True)
        ipfs_hash = result.stdout.strip()
        
        # Clean up
        os.remove(tmp_path)
    except subprocess.CalledProcessError as e:
        print(f"Failed to publish to IPFS: {e}. Storing locally only.")
    except Exception as e:
        print(f"Unexpected error with IPFS: {e}. Storing locally only.")
    
    # Store locally
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO posts (user, content, timestamp, ipfs_hash) VALUES (?, ?, ?, ?)",
              (username, content, post_data["timestamp"], ipfs_hash))
    conn.commit()
    conn.close()
    
    # Update profile with post hash
    update_profile(username, ipfs_hash)

# Follow a user by IPNS key (auto-discover username)
def follow(ipns_key):
    get_own_username()  # Ensure own username is set, even if not used directly
    ipfs_handler = IpfsSetupHandler()
    ipfs_handler.ensure_running()
    try:
        # Resolve IPNS to get latest profile hash
        result = subprocess.run(['ipfs', 'name', 'resolve', ipns_key], capture_output=True, text=True, check=True)
        resolved_path = result.stdout.strip()  # /ipfs/Qm...
        profile_hash = resolved_path.replace('/ipfs/', '')
        
        # Fetch profile to get username
        result = subprocess.run(['ipfs', 'cat', profile_hash], capture_output=True, text=True, check=True)
        profile = json.loads(result.stdout)
        target_username = profile.get("username")
        if not target_username:
            raise ValueError("Profile does not contain a username.")
        
        # Store in follows table
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO follows (username, ipns_key) VALUES (?, ?)",
                  (target_username, ipns_key))
        conn.commit()
        conn.close()
        print(f"Following {target_username} with IPNS key {ipns_key}")
    except subprocess.CalledProcessError as e:
        print(f"Error resolving/fetching profile: {e}")
    except Exception as e:
        print(f"Error following user: {e}")

# View feed
def view_feed(limit):
    username = get_own_username()  # Ensure set, though not directly used
    ipfs_handler = IpfsSetupHandler()
    ipfs_handler.ensure_running()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get followed users
    c.execute("SELECT username, ipns_key FROM follows")
    follows = c.fetchall()
    
    # Fetch posts from local storage
    posts = []
    c.execute("SELECT user, content, timestamp FROM posts ORDER BY timestamp ASC")
    posts.extend(c.fetchall())
    
    # Fetch posts from followed users via IPNS and IPFS (on-demand)
    for follow_username, ipns_key in follows:
        if ipns_key:
            try:
                # Resolve IPNS to get latest profile hash with animation
                cmd = ['ipfs', 'name', 'resolve', ipns_key]
                print(f"Resolving IPNS for {follow_username}... ", end='', flush=True)
                spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                while process.poll() is None:
                    sys.stdout.write(next(spinner))
                    sys.stdout.flush()
                    time.sleep(0.2)
                    sys.stdout.write('\b')
                stdout, stderr = process.communicate()
                print()  # Newline after spinner
                if process.returncode != 0:
                    print(f"Error resolving IPNS for {follow_username}: {stderr.strip()}")
                    continue
                resolved_path = stdout.strip()  # /ipfs/Qm...
                profile_hash = resolved_path.replace('/ipfs/', '')
                
                # Fetch profile (contains post hashes)
                result = subprocess.run(['ipfs', 'cat', profile_hash], capture_output=True, text=True, check=True)
                profile = json.loads(result.stdout)
                post_hashes = profile.get("posts", [])
                for post_hash in post_hashes:
                    try:
                        result = subprocess.run(['ipfs', 'cat', post_hash], capture_output=True, text=True, check=True)
                        post = json.loads(result.stdout)
                        posts.append((post["user"], post["content"], post["timestamp"]))
                    except subprocess.CalledProcessError as e:
                        print(f"Error fetching post {post_hash} for {follow_username}: {e}")
            except Exception as e:
                print(f"Unexpected error fetching posts for {follow_username}: {e}")
    
    conn.close()
    
    # Sort and display posts
    posts.sort(key=lambda x: x[2])
    for user, content, timestamp in posts[-limit:]:
        header = f"{WHITE}@{user}<{time.ctime(timestamp)}>{RESET}"
        lines = content.splitlines()
        if lines and not lines[0].startswith(">>> "):
            print(f"{header} {BLUE}{lines[0]}{RESET}")
            start_idx = 1
        else:
            print(header)
            start_idx = 0
        for line in lines[start_idx:]:
            if line.startswith(">>> "):
                print(f"{GREEN}{line}{RESET}")
            else:
                print(f"{BLUE}{line}{RESET}")

# Main CLI
def main():
    # Print ASCII art on startup
    print(ASCII_ART)
    
    # Ensure IPFS is set up at the start
    ipfs_handler = IpfsSetupHandler()
    ipfs_handler.ensure_running()
    
    parser = argparse.ArgumentParser(
        description="Decentralized Terminal Social Network",
        epilog="Examples:\n"
               "  python main.py \"Your post message\"  # Post a message\n"
               "  python main.py \"Message\" file.txt   # Post message + file content\n"
               "  python main.py --follow <ipns_key>   # Follow a user by IPNS key\n"
               "  python main.py --feed                # View your feed\n"
               "  python main.py --config              # Edit configuration file",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("args", nargs="*", help="Message parts or files to post (positional for convenience)")
    parser.add_argument("--post", help="Content to post (alternative to positional args)")
    parser.add_argument("--follow", help="IPNS key of the user to follow")
    parser.add_argument("--feed", action="store_true", help="View the feed")
    parser.add_argument("--config", action="store_true", help="Edit configuration file in vim")
    parser.add_argument("--limit", type=int, default=10, help="Number of feed items to show (default: 10)")
    args = parser.parse_args()
    
    # Handle flagged actions first
    if args.config:
        if args.args or args.post or args.follow or args.feed:
            parser.error("--config cannot be combined with other actions.")
        init()
        try:
            subprocess.run(['vim', CONFIG_PATH], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error opening vim: {e}")
        except FileNotFoundError:
            print("Error: 'vim' command not found. Please install vim or edit ~/.sclik/config.json manually.")
        return
    elif args.follow:
        if args.args or args.post or args.feed or args.config:
            parser.error("--follow cannot be combined with other actions.")
        init()
        follow(args.follow)
        return
    elif args.feed:
        if args.args or args.post or args.follow or args.config:
            parser.error("--feed cannot be combined with other actions.")
        init()
        view_feed(args.limit)
        return
    elif args.post:
        if args.args or args.follow or args.feed or args.config:
            parser.error("--post cannot be combined with positional args or other actions.")
        init()
        post(args.post)
        return
    
    # Handle positional args for posting (message parts and/or files)
    if args.args:
        parts = []
        for arg in args.args:
            if os.path.isfile(arg):
                try:
                    with open(arg, 'r') as f:
                        file_content = f.read().strip()
                    full_path = os.path.abspath(arg)
                    parts.append(f">>> {full_path}\n{file_content}")
                except Exception as e:
                    print(f"Error reading file {arg}: {e}")
                    continue
            else:
                parts.append(arg)
        if not parts:
            parser.error("No valid content provided for post.")
        content = "\n\n".join(parts)
        init()
        post(content)
        return
    
    # If no action, show help
    parser.print_help()

if __name__ == "__main__":
    main()
