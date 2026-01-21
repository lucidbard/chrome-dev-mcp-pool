"""
Chrome Pool Manager - Windows Service
Manages a pool of Chrome instances with remote debugging enabled.
"""
import asyncio
import json
import logging
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Configuration
CHROME_PATH_WSL = "/usr/bin/google-chrome"  # WSL Chrome path (headless)
CHROME_PATH_WINDOWS = r"C:\Program Files\Google\Chrome\Application\chrome.exe"  # Windows Chrome path (GUI)
WINDOWS_HOST = "stark-windows"  # SSH host for Windows
PORT_RANGE = range(9222, 9233)  # Ports 9222-9232 (11 instances)
DATA_DIR = Path.home() / ".local" / "share" / "chrome-pool-manager"
DB_PATH = DATA_DIR / "pool.db"
IDLE_TIMEOUT = 300  # 5 minutes

# Logging
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "service.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Models
class AllocationRequest(BaseModel):
    agent_id: str
    url: Optional[str] = "about:blank"
    timeout: int = 300  # seconds
    mode: str = "headless"  # "headless" (WSL) or "gui" (Windows)


class AllocationResponse(BaseModel):
    instance_id: str
    debug_port: int
    agent_id: str
    expires_at: str


class InstanceStatus(BaseModel):
    instance_id: str
    port: int
    pid: Optional[int]
    status: str  # 'idle', 'allocated', 'starting', 'crashed'
    mode: Optional[str]  # 'headless' or 'gui'
    agent_id: Optional[str]
    allocated_at: Optional[str]
    expires_at: Optional[str]


# Database
def init_db():
    """Initialize SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            instance_id TEXT PRIMARY KEY,
            port INTEGER UNIQUE,
            pid INTEGER,
            status TEXT,
            mode TEXT,
            agent_id TEXT,
            allocated_at TEXT,
            expires_at TEXT,
            last_heartbeat TEXT,
            tunnel_pid INTEGER
        )
    """)
    conn.commit()
    conn.close()


def get_db():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)


# Chrome Process Management
class ChromeInstance:
    def __init__(self, instance_id: str, port: int):
        self.instance_id = instance_id
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.tunnel_pid: Optional[int] = None
        self.mode: Optional[str] = None

    def start(self, url: str = "about:blank", mode: str = "headless"):
        """Start Chrome with remote debugging."""
        self.mode = mode

        if mode == "headless":
            return self._start_headless(url)
        elif mode == "gui":
            return self._start_gui(url)
        else:
            logger.error(f"Unknown mode: {mode}")
            return False

    def _start_headless(self, url: str) -> bool:
        """Start Chrome in headless mode on WSL."""
        user_data_dir = DATA_DIR / "profiles" / f"chrome-{self.port}"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [
            CHROME_PATH_WSL,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={user_data_dir}",
            "--headless=new",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--no-first-run",
            "--disable-sync",
            "--disable-gpu",
            "--no-sandbox",  # Required for WSL
            url
        ]

        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.pid = self.process.pid
            logger.info(f"Started headless Chrome {self.instance_id} on port {self.port} (PID: {self.pid})")
            return True
        except Exception as e:
            logger.error(f"Failed to start headless Chrome {self.instance_id}: {e}")
            return False

    def _start_gui(self, url: str) -> bool:
        """Start Chrome with GUI on Windows via scheduled task."""
        # Windows user data dir
        win_user_data_dir = f"C:\\Users\\john\\AppData\\Local\\chrome-pool\\chrome-{self.port}"

        # Task name for this instance
        task_name = f"ChromePool_{self.port}"

        # PowerShell script content
        ps_script = f"""Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {{$_.CommandLine -like "*--remote-debugging-port={self.port}*"}} | Stop-Process -Force
Start-Process '{CHROME_PATH_WINDOWS}' -ArgumentList '--remote-debugging-port={self.port}', '--user-data-dir={win_user_data_dir}', '--no-first-run', '{url}'
"""

        # Create temp script file paths
        local_script = f"/tmp/chrome-pool-{self.port}.ps1"
        windows_script = f"C:\\Users\\john\\AppData\\Local\\Temp\\chrome-pool-{self.port}.ps1"

        try:
            # Write script to local temp file
            with open(local_script, 'w') as f:
                f.write(ps_script)

            # Copy script to Windows via SCP
            subprocess.run(
                ["scp", local_script, f"{WINDOWS_HOST}:{windows_script}"],
                capture_output=True,
                timeout=5
            )

            # Delete existing task if it exists
            subprocess.run(
                ["ssh", WINDOWS_HOST, "schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True,
                timeout=5
            )

            # Create scheduled task (runs in interactive session)
            create_task = subprocess.run(
                ["ssh", WINDOWS_HOST, "schtasks", "/Create", "/TN", task_name,
                 "/TR", f"\"powershell -ExecutionPolicy Bypass -File {windows_script}\"",
                 "/SC", "ONCE", "/ST", "00:00", "/F"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if create_task.returncode != 0:
                logger.error(f"Failed to create scheduled task: {create_task.stderr}")
                return False

            # Run the task immediately
            run_task = subprocess.run(
                ["ssh", WINDOWS_HOST, "schtasks", "/Run", "/TN", task_name],
                capture_output=True,
                text=True,
                timeout=5
            )

            if run_task.returncode != 0:
                logger.error(f"Failed to run scheduled task: {run_task.stderr}")
                return False

            logger.info(f"Started GUI Chrome {self.instance_id} on Windows via task {task_name})")

            # Wait for Chrome to start
            time.sleep(2)

            # Kill any existing SSH tunnels for this port
            try:
                subprocess.run(
                    ["pkill", "-f", f"ssh.*-L.*{self.port}:"],
                    timeout=2
                )
                logger.info(f"Killed existing SSH tunnels for port {self.port}")
            except Exception as e:
                logger.warning(f"Error killing existing tunnels: {e}")

            # Create SSH tunnel from WSL to Windows
            tunnel_cmd = [
                "ssh",
                "-f",  # Background
                "-N",  # No command
                "-L", f"{self.port}:127.0.0.1:{self.port}",  # Local forward
                WINDOWS_HOST
            ]

            tunnel_process = subprocess.Popen(
                tunnel_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self.tunnel_pid = tunnel_process.pid
            self.pid = None  # PID not easily retrievable from scheduled task

            logger.info(f"Created SSH tunnel for port {self.port} (tunnel PID: {self.tunnel_pid})")

            # Verify Chrome is listening on Windows
            time.sleep(4)
            # Use netstat for faster port check than Test-NetConnection
            ps_verify = f'netstat -an | Select-String ":{self.port} " | Select-String "LISTENING"'
            verify_cmd = subprocess.run(
                ["ssh", WINDOWS_HOST, "powershell", "-Command", f'"{ps_verify}"'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if not verify_cmd.stdout.strip():
                logger.error(f"Chrome not listening on port {self.port}")
                logger.error(f"Verification stdout: {verify_cmd.stdout.strip()}")
                logger.error(f"Verification stderr: {verify_cmd.stderr}")
                return False

            logger.info(f"Verified Chrome listening on port {self.port}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout starting Chrome on Windows for {self.instance_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to start GUI Chrome {self.instance_id}: {e}")
            return False

    def stop(self):
        """Stop Chrome instance."""
        if self.mode == "headless":
            self._stop_headless()
        elif self.mode == "gui":
            self._stop_gui()

    def _stop_headless(self):
        """Stop headless Chrome on WSL."""
        if self.pid:
            try:
                process = psutil.Process(self.pid)
                # Kill all child processes too
                for child in process.children(recursive=True):
                    child.kill()
                process.kill()
                logger.info(f"Stopped headless Chrome {self.instance_id} (PID: {self.pid})")
            except psutil.NoSuchProcess:
                logger.warning(f"Process {self.pid} not found")
            except Exception as e:
                logger.error(f"Error stopping instance {self.instance_id}: {e}")
            finally:
                self.pid = None
                self.process = None

    def _stop_gui(self):
        """Stop GUI Chrome on Windows and close SSH tunnel."""
        logger.info(f"Stopping GUI Chrome {self.instance_id}")

        # Kill SSH tunnel by port pattern (more reliable than PID due to -f flag)
        try:
            result = subprocess.run(
                ["pkill", "-f", f"ssh.*-L.*{self.port}:"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Killed SSH tunnel for {self.instance_id} on port {self.port}")
            else:
                logger.debug(f"No SSH tunnel found for port {self.port}")
        except Exception as e:
            logger.error(f"Error killing tunnel: {e}")
        finally:
            self.tunnel_pid = None

        # Delete scheduled task
        task_name = f"ChromePool_{self.port}"
        try:
            subprocess.run(
                ["ssh", WINDOWS_HOST, "schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True,
                timeout=5
            )
            logger.info(f"Deleted scheduled task {task_name}")
        except Exception as e:
            logger.error(f"Error deleting scheduled task: {e}")

        # Kill Chrome process by port (more reliable than CommandLine matching)
        # Note: Must wrap entire PowerShell command in quotes for SSH
        kill_cmd = f'powershell -Command "$line = netstat -ano | Select-String \\"127.0.0.1:{self.port} .*LISTENING\\"; if ($line) {{ $procId = ($line -split \\" +\\")[-1]; Write-Host \\"Killing PID: $procId\\"; Stop-Process -Id $procId -Force }} else {{ Write-Host \\"No process found on port {self.port}\\" }}"'
        try:
            result = subprocess.run(
                ["ssh", WINDOWS_HOST, kill_cmd],
                capture_output=True,
                timeout=5,
                text=True,
                shell=False
            )

            # Log output for debugging
            if result.stdout:
                logger.info(f"Kill command output: {result.stdout.strip()}")
            if result.stderr:
                logger.error(f"Kill command error: {result.stderr.strip()}")
            if result.returncode != 0:
                logger.error(f"Kill command failed with return code {result.returncode}")
            else:
                logger.info(f"Kill command succeeded for {self.instance_id} on port {self.port}")

            # Wait for port to be released (up to 8 seconds - Windows takes time to release ports)
            port_released = False
            for i in range(8):
                time.sleep(1)
                check_cmd = f'Test-NetConnection -ComputerName localhost -Port {self.port} -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded'
                verify = subprocess.run(
                    ["ssh", WINDOWS_HOST, "powershell", "-Command", check_cmd],
                    capture_output=True,
                    timeout=5
                )
                if verify.stdout.strip() == b"False":
                    logger.info(f"Port {self.port} released after {i+1}s")
                    port_released = True
                    break

            if not port_released:
                logger.warning(f"Port {self.port} still in use after 8s (Windows port release can be slow)")

        except Exception as e:
            logger.error(f"Error stopping Chrome on Windows: {e}")
        finally:
            self.pid = None

    def is_alive(self) -> bool:
        """Check if Chrome process is still running."""
        if not self.pid:
            return False
        try:
            process = psutil.Process(self.pid)
            return process.is_running()
        except psutil.NoSuchProcess:
            return False


# Pool Manager
class ChromePoolManager:
    def __init__(self):
        self.instances: dict[int, ChromeInstance] = {}
        init_db()

    def cleanup_orphaned_tunnels(self):
        """Kill orphaned SSH tunnels from previous sessions."""
        logger.info("Cleaning up orphaned SSH tunnels...")
        try:
            # Find and kill any SSH tunnels for our port range
            for port in PORT_RANGE:
                subprocess.run(
                    ["pkill", "-f", f"ssh.*-L.*{port}:"],
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
            logger.info("Orphaned tunnel cleanup complete")
        except Exception as e:
            logger.error(f"Error cleaning up tunnels: {e}")

    def initialize_pool(self):
        """Initialize Chrome instance pool."""
        logger.info("Initializing Chrome pool...")

        # Clean up orphaned tunnels from previous sessions
        self.cleanup_orphaned_tunnels()

        conn = get_db()
        cursor = conn.cursor()

        for port in PORT_RANGE:
            instance_id = f"chrome-{port}"

            # Check if instance exists in DB
            cursor.execute(
                "SELECT * FROM instances WHERE instance_id = ?",
                (instance_id,)
            )
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO instances
                    (instance_id, port, status, mode, pid, agent_id, allocated_at, expires_at, last_heartbeat, tunnel_pid)
                    VALUES (?, ?, 'idle', NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """, (instance_id, port))

            self.instances[port] = ChromeInstance(instance_id, port)

        conn.commit()
        conn.close()
        logger.info(f"Pool initialized with {len(PORT_RANGE)} instances")

    def allocate_instance(self, agent_id: str, url: str, timeout: int, mode: str = "headless") -> Optional[AllocationResponse]:
        """Allocate a Chrome instance to an agent."""
        conn = get_db()
        cursor = conn.cursor()

        # Check if agent already has an instance
        cursor.execute(
            "SELECT instance_id, port, expires_at FROM instances WHERE agent_id = ? AND status = 'allocated'",
            (agent_id,)
        )
        existing = cursor.fetchone()
        if existing:
            logger.info(f"Agent {agent_id} already has instance {existing[0]}")
            return AllocationResponse(
                instance_id=existing[0],
                debug_port=existing[1],
                agent_id=agent_id,
                expires_at=existing[2]
            )

        # Find idle instance
        cursor.execute(
            "SELECT instance_id, port FROM instances WHERE status = 'idle' LIMIT 1"
        )
        available = cursor.fetchone()

        if not available:
            logger.warning(f"No available instances for agent {agent_id}")
            conn.close()
            return None

        instance_id, port = available
        instance = self.instances[port]

        # Start Chrome
        cursor.execute(
            "UPDATE instances SET status = 'starting', mode = ? WHERE instance_id = ?",
            (mode, instance_id)
        )
        conn.commit()

        if not instance.start(url, mode):
            cursor.execute(
                "UPDATE instances SET status = 'crashed' WHERE instance_id = ?",
                (instance_id,)
            )
            conn.commit()
            conn.close()
            return None

        # Update allocation
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=timeout)

        cursor.execute("""
            UPDATE instances
            SET status = 'allocated',
                mode = ?,
                pid = ?,
                agent_id = ?,
                allocated_at = ?,
                expires_at = ?,
                last_heartbeat = ?,
                tunnel_pid = ?
            WHERE instance_id = ?
        """, (mode, instance.pid, agent_id, now.isoformat(), expires_at.isoformat(), now.isoformat(), instance.tunnel_pid, instance_id))

        conn.commit()
        conn.close()

        logger.info(f"Allocated instance {instance_id} to agent {agent_id}")

        return AllocationResponse(
            instance_id=instance_id,
            debug_port=port,
            agent_id=agent_id,
            expires_at=expires_at.isoformat()
        )

    def release_instance(self, instance_id: str, agent_id: Optional[str] = None) -> bool:
        """Release a Chrome instance."""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT port, agent_id, tunnel_pid, mode, pid FROM instances WHERE instance_id = ?",
            (instance_id,)
        )
        result = cursor.fetchone()

        if not result:
            conn.close()
            return False

        port, current_agent, tunnel_pid, mode, pid = result

        # Verify agent owns this instance (if agent_id provided)
        if agent_id and current_agent != agent_id:
            logger.warning(f"Agent {agent_id} tried to release instance owned by {current_agent}")
            conn.close()
            return False

        # Stop Chrome - restore state from database first
        instance = self.instances.get(port)
        if instance:
            # Restore database state to instance object
            instance.tunnel_pid = tunnel_pid
            instance.mode = mode
            instance.pid = pid
            instance.stop()

        # Update DB
        cursor.execute("""
            UPDATE instances
            SET status = 'idle',
                mode = NULL,
                pid = NULL,
                agent_id = NULL,
                allocated_at = NULL,
                expires_at = NULL,
                last_heartbeat = NULL,
                tunnel_pid = NULL
            WHERE instance_id = ?
        """, (instance_id,))

        conn.commit()
        conn.close()

        logger.info(f"Released instance {instance_id}")
        return True

    def get_instance_status(self, instance_id: str) -> Optional[InstanceStatus]:
        """Get status of a Chrome instance."""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM instances WHERE instance_id = ?",
            (instance_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return InstanceStatus(
            instance_id=row[0],
            port=row[1],
            pid=row[2],
            status=row[3],
            mode=row[4],
            agent_id=row[5],
            allocated_at=row[6],
            expires_at=row[7]
        )

    def list_instances(self) -> list[InstanceStatus]:
        """List all Chrome instances."""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM instances")
        rows = cursor.fetchall()
        conn.close()

        return [
            InstanceStatus(
                instance_id=row[0],
                port=row[1],
                pid=row[2],
                status=row[3],
                mode=row[4],
                agent_id=row[5],
                allocated_at=row[6],
                expires_at=row[7]
            )
            for row in rows
        ]

    def cleanup_expired(self):
        """Clean up expired allocations."""
        conn = get_db()
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat()
        cursor.execute(
            "SELECT instance_id FROM instances WHERE status = 'allocated' AND expires_at < ?",
            (now,)
        )
        expired = cursor.fetchall()
        conn.close()

        for (instance_id,) in expired:
            logger.info(f"Releasing expired instance {instance_id}")
            self.release_instance(instance_id)

    def cleanup_crashed(self):
        """Detect and clean up crashed instances."""
        for port, instance in self.instances.items():
            if instance.pid and not instance.is_alive():
                logger.warning(f"Detected crashed instance {instance.instance_id}")
                self.release_instance(instance.instance_id)

    async def monitoring_loop(self):
        """Background monitoring loop."""
        while True:
            try:
                self.cleanup_expired()
                self.cleanup_crashed()
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)  # Check every 30 seconds


# FastAPI App
pool_manager = ChromePoolManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager."""
    # Startup
    pool_manager.initialize_pool()
    monitoring_task = asyncio.create_task(pool_manager.monitoring_loop())

    yield

    # Shutdown
    monitoring_task.cancel()
    logger.info("Shutting down Chrome pool...")
    for instance in pool_manager.instances.values():
        instance.stop()


app = FastAPI(
    title="Chrome Pool Manager",
    description="Manages a pool of Chrome instances with remote debugging",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/instance/allocate", response_model=AllocationResponse)
async def allocate_instance(request: AllocationRequest):
    """Allocate a Chrome instance to an agent."""
    result = pool_manager.allocate_instance(
        request.agent_id,
        request.url or "about:blank",
        request.timeout,
        request.mode
    )

    if not result:
        raise HTTPException(status_code=503, detail="No available Chrome instances")

    return result


@app.post("/instance/{instance_id}/release")
async def release_instance(instance_id: str, agent_id: Optional[str] = None):
    """Release a Chrome instance."""
    success = pool_manager.release_instance(instance_id, agent_id)

    if not success:
        raise HTTPException(status_code=404, detail="Instance not found")

    return {"status": "released", "instance_id": instance_id}


@app.get("/instance/{instance_id}/status", response_model=InstanceStatus)
async def get_instance_status(instance_id: str):
    """Get status of a Chrome instance."""
    status = pool_manager.get_instance_status(instance_id)

    if not status:
        raise HTTPException(status_code=404, detail="Instance not found")

    return status


@app.get("/instances", response_model=list[InstanceStatus])
async def list_instances():
    """List all Chrome instances."""
    return pool_manager.list_instances()


@app.post("/instance/{instance_id}/heartbeat")
async def heartbeat(instance_id: str, agent_id: str):
    """Update heartbeat for an instance."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE instances SET last_heartbeat = ? WHERE instance_id = ? AND agent_id = ?",
        (datetime.utcnow().isoformat(), instance_id, agent_id)
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Instance not found or agent mismatch")

    conn.commit()
    conn.close()

    return {"status": "ok"}


@app.get("/stream")
async def stream_events():
    """HTTP stream of pool events (chunked transfer encoding)."""
    async def event_generator():
        """Generate events in newline-delimited JSON format."""
        while True:
            try:
                instances = pool_manager.list_instances()
                event = {
                    "type": "status_update",
                    "timestamp": datetime.utcnow().isoformat(),
                    "instances": [inst.model_dump() for inst in instances]
                }
                yield json.dumps(event) + "\n"
                await asyncio.sleep(5)  # Update every 5 seconds
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                break

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
