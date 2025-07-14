# ~/Apps/sclik/app/ipfs_setup_handler.py
import os
import sys
import time
import subprocess
import tempfile

class IpfsSetupHandler:
    def __init__(self):
        self.ipfs_bin = os.path.join(os.path.expanduser('~'), '.local', 'bin', 'ipfs')
        self.ipfs_home = os.path.expanduser('~/.ipfs')
        self.service_name = 'ipfs.service'
        self.service_dir = os.path.join(os.path.expanduser('~'), '.config', 'systemd', 'user')
        os.makedirs(os.path.dirname(self.ipfs_bin), exist_ok=True)

    def install_ipfs(self):
        url = "https://dist.ipfs.tech/kubo/v0.35.0/kubo_v0.35.0_linux-amd64.tar.gz"
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                subprocess.run(['wget', url], check=True)
                file_name = os.path.basename(url)
                subprocess.run(['tar', '-xvzf', file_name], check=True)
                subprocess.run(['cp', 'kubo/ipfs', self.ipfs_bin], check=True)
                os.chmod(self.ipfs_bin, 0o755)  # Ensure executable
            except subprocess.CalledProcessError as e:
                print(f"Error during IPFS installation: {e}")
                sys.exit(1)
            finally:
                os.chdir(original_dir)

    def init_ipfs(self):
        if not os.path.exists(self.ipfs_home):
            try:
                subprocess.run([self.ipfs_bin, 'init'], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Failed to initialize IPFS: {e}")
                sys.exit(1)

    def setup_service(self):
        service_path = os.path.join(self.service_dir, self.service_name)
        os.makedirs(self.service_dir, exist_ok=True)

        service_content = f"""[Unit]
Description=IPFS Daemon

[Service]
ExecStart={self.ipfs_bin} daemon
Restart=always

[Install]
WantedBy=default.target
"""

        with open(service_path, 'w') as f:
            f.write(service_content)

        try:
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', self.service_name], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to set up IPFS service: {e}")
            print("Note: This setup assumes systemd with user services support. If your system doesn't support this, please run IPFS manually.")
            sys.exit(1)

    def is_running(self):
        try:
            result = subprocess.run(['systemctl', '--user', 'is-active', self.service_name], capture_output=True, text=True)
            return result.returncode == 0 and result.stdout.strip() == 'active'
        except FileNotFoundError:
            # If systemctl not found, fallback to manual check
            return self._manual_check()
        except subprocess.CalledProcessError:
            return False

    def _manual_check(self):
        try:
            subprocess.run([self.ipfs_bin, 'swarm', 'peers'], capture_output=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def ensure_running(self):
        if self.is_running():
            return

        if not os.path.exists(self.ipfs_bin):
            print("IPFS not installed. Installing now...")
            self.install_ipfs()

        self.init_ipfs()

        if not self.is_running():
            print("Setting up IPFS as a systemd user service to ensure it keeps running.")
            self.setup_service()

        # Wait for daemon to start
        for _ in range(30):
            if self.is_running():
                print("IPFS daemon is now running.")
                return
            time.sleep(1)

        raise RuntimeError("Failed to start IPFS daemon after setup.")
