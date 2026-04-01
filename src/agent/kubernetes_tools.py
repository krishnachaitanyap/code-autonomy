"""
Built-in Kubernetes tools for agent execution.

Provides safe kubectl wrappers that agents can invoke to inspect, manage,
and troubleshoot Kubernetes clusters. Supports both direct kubectl execution
and MCP server delegation.
"""

import json
import logging
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _run_kubectl(args: list[str], kubeconfig: str = "", context: str = "", namespace: str = "", timeout: int = 30) -> tuple[int, str, str]:
    """Run a kubectl command with optional kubeconfig/context/namespace."""
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    if context:
        cmd.extend(["--context", context])
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(args)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", "kubectl not found. Install kubectl to use Kubernetes tools."
    except subprocess.TimeoutExpired:
        return 124, "", f"kubectl command timed out after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


# ---------------------------------------------------------------------------
# Tool definitions (registered as agent tools)
# ---------------------------------------------------------------------------

KUBERNETES_TOOLS = [
    {
        "name": "k8s_get_pods",
        "description": "List pods in a namespace with their status, restarts, and age. Use to check if services are running.",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace (default: 'default')", "default": "default"},
            "label_selector": {"type": "string", "description": "Filter by label (e.g., 'app=myservice')", "default": ""},
            "all_namespaces": {"type": "boolean", "description": "List pods across all namespaces", "default": False},
        },
    },
    {
        "name": "k8s_get_services",
        "description": "List services in a namespace with their type, cluster IP, and ports.",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "all_namespaces": {"type": "boolean", "description": "List across all namespaces", "default": False},
        },
    },
    {
        "name": "k8s_get_deployments",
        "description": "List deployments with replica status (desired/available/ready).",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "all_namespaces": {"type": "boolean", "description": "List across all namespaces", "default": False},
        },
    },
    {
        "name": "k8s_describe",
        "description": "Get detailed description of a Kubernetes resource (pod, service, deployment, etc.).",
        "parameters": {
            "resource_type": {"type": "string", "description": "Resource type (pod, service, deployment, configmap, etc.)"},
            "name": {"type": "string", "description": "Resource name"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_logs",
        "description": "Get logs from a pod. Essential for debugging application errors and crashes.",
        "parameters": {
            "pod_name": {"type": "string", "description": "Pod name"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "container": {"type": "string", "description": "Container name (for multi-container pods)", "default": ""},
            "tail_lines": {"type": "integer", "description": "Number of lines from the end", "default": 100},
            "previous": {"type": "boolean", "description": "Get logs from previous container instance (for crash debugging)", "default": False},
        },
    },
    {
        "name": "k8s_get_events",
        "description": "List recent cluster events. Useful for debugging scheduling, scaling, and health issues.",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "field_selector": {"type": "string", "description": "Filter events (e.g., 'involvedObject.name=mypod')", "default": ""},
        },
    },
    {
        "name": "k8s_get_nodes",
        "description": "List cluster nodes with their status, roles, and resource capacity.",
        "parameters": {},
    },
    {
        "name": "k8s_top_pods",
        "description": "Show CPU and memory usage of pods (requires metrics-server).",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "all_namespaces": {"type": "boolean", "description": "Show across all namespaces", "default": False},
        },
    },
    {
        "name": "k8s_get_configmap",
        "description": "Get contents of a ConfigMap.",
        "parameters": {
            "name": {"type": "string", "description": "ConfigMap name"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_get_ingress",
        "description": "List ingress rules showing hosts, paths, and backend services.",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "all_namespaces": {"type": "boolean", "description": "List across all namespaces", "default": False},
        },
    },
    {
        "name": "k8s_rollout_status",
        "description": "Check rollout status of a deployment. Shows if a deploy is progressing or stuck.",
        "parameters": {
            "deployment_name": {"type": "string", "description": "Deployment name"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_scale",
        "description": "Scale a deployment to a specific number of replicas.",
        "parameters": {
            "deployment_name": {"type": "string", "description": "Deployment name"},
            "replicas": {"type": "integer", "description": "Target replica count"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_rollout_restart",
        "description": "Restart all pods of a deployment (rolling restart, zero downtime).",
        "parameters": {
            "deployment_name": {"type": "string", "description": "Deployment name"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_exec",
        "description": "Execute a command inside a running pod container.",
        "parameters": {
            "pod_name": {"type": "string", "description": "Pod name"},
            "command": {"type": "string", "description": "Command to execute"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
            "container": {"type": "string", "description": "Container name (for multi-container pods)", "default": ""},
        },
    },
    {
        "name": "k8s_apply",
        "description": "Apply a Kubernetes manifest from a YAML file or inline YAML string.",
        "parameters": {
            "manifest": {"type": "string", "description": "YAML manifest content or file path"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_get_namespaces",
        "description": "List all namespaces in the cluster.",
        "parameters": {},
    },
    {
        "name": "k8s_port_forward",
        "description": "Set up port forwarding to a pod (returns the command to run, does not block).",
        "parameters": {
            "pod_name": {"type": "string", "description": "Pod name"},
            "local_port": {"type": "integer", "description": "Local port"},
            "remote_port": {"type": "integer", "description": "Pod port"},
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
    {
        "name": "k8s_get_secrets",
        "description": "List secrets in a namespace (names only, not values for security).",
        "parameters": {
            "namespace": {"type": "string", "description": "Kubernetes namespace", "default": "default"},
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution dispatcher
# ---------------------------------------------------------------------------

# Blocked commands that should never be run by an agent
BLOCKED_PATTERNS = ["delete namespace", "delete node", "delete pv ", "drain", "cordon", "taint"]


def execute_k8s_tool(tool_name: str, args: dict, config: dict = None) -> str:
    """Execute a Kubernetes tool and return the result as a string."""
    cfg = config or {}
    kubeconfig = cfg.get("kubeconfig", "")
    context = cfg.get("context", "")
    timeout = int(cfg.get("timeout", 30))

    ns = args.get("namespace", "default")
    all_ns = args.get("all_namespaces", False)

    def _kubectl(cmd_args: list[str], ns_override: str = "") -> str:
        use_ns = ns_override or ("" if all_ns else ns)
        extra = ["-A"] if all_ns else []
        code, out, err = _run_kubectl(cmd_args + extra, kubeconfig=kubeconfig, context=context, namespace=use_ns, timeout=timeout)
        if code != 0:
            return f"Error (exit {code}): {err.strip()}" if err else f"Error (exit {code})"
        return out.strip() if out.strip() else "(no output)"

    if tool_name == "k8s_get_pods":
        cmd = ["get", "pods", "-o", "wide"]
        if args.get("label_selector"):
            cmd.extend(["-l", args["label_selector"]])
        return _kubectl(cmd)

    elif tool_name == "k8s_get_services":
        return _kubectl(["get", "services", "-o", "wide"])

    elif tool_name == "k8s_get_deployments":
        return _kubectl(["get", "deployments", "-o", "wide"])

    elif tool_name == "k8s_describe":
        return _kubectl(["describe", args.get("resource_type", "pod"), args.get("name", "")])

    elif tool_name == "k8s_logs":
        cmd = ["logs", args.get("pod_name", ""), f"--tail={args.get('tail_lines', 100)}"]
        if args.get("container"):
            cmd.extend(["-c", args["container"]])
        if args.get("previous"):
            cmd.append("--previous")
        return _kubectl(cmd)

    elif tool_name == "k8s_get_events":
        cmd = ["get", "events", "--sort-by=.lastTimestamp"]
        if args.get("field_selector"):
            cmd.extend(["--field-selector", args["field_selector"]])
        return _kubectl(cmd)

    elif tool_name == "k8s_get_nodes":
        return _kubectl(["get", "nodes", "-o", "wide"], ns_override="")

    elif tool_name == "k8s_top_pods":
        return _kubectl(["top", "pods"])

    elif tool_name == "k8s_get_configmap":
        return _kubectl(["get", "configmap", args.get("name", ""), "-o", "yaml"])

    elif tool_name == "k8s_get_ingress":
        return _kubectl(["get", "ingress", "-o", "wide"])

    elif tool_name == "k8s_rollout_status":
        return _kubectl(["rollout", "status", f"deployment/{args.get('deployment_name', '')}"])

    elif tool_name == "k8s_scale":
        replicas = args.get("replicas", 1)
        return _kubectl(["scale", f"deployment/{args.get('deployment_name', '')}", f"--replicas={replicas}"])

    elif tool_name == "k8s_rollout_restart":
        return _kubectl(["rollout", "restart", f"deployment/{args.get('deployment_name', '')}"])

    elif tool_name == "k8s_exec":
        command = args.get("command", "")
        # Safety check
        for blocked in BLOCKED_PATTERNS:
            if blocked in command.lower():
                return f"Blocked: '{blocked}' is not allowed for safety reasons."
        cmd = ["exec", args.get("pod_name", ""), "--"]
        if args.get("container"):
            cmd = ["exec", args.get("pod_name", ""), "-c", args["container"], "--"]
        cmd.extend(["sh", "-c", command])
        return _kubectl(cmd)

    elif tool_name == "k8s_apply":
        manifest = args.get("manifest", "")
        if manifest.endswith((".yml", ".yaml")):
            return _kubectl(["apply", "-f", manifest])
        else:
            # Inline YAML — write to temp file
            import tempfile, os
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                f.write(manifest)
                f.flush()
                result = _kubectl(["apply", "-f", f.name])
            os.unlink(f.name)
            return result

    elif tool_name == "k8s_get_namespaces":
        return _kubectl(["get", "namespaces"], ns_override="")

    elif tool_name == "k8s_port_forward":
        local = args.get("local_port", 8080)
        remote = args.get("remote_port", 80)
        pod = args.get("pod_name", "")
        return f"Run: kubectl port-forward {pod} {local}:{remote} -n {ns}\n(Port forwarding runs in foreground — use & to background)"

    elif tool_name == "k8s_get_secrets":
        return _kubectl(["get", "secrets"])

    else:
        return f"Unknown Kubernetes tool: {tool_name}"


def get_k8s_tool_definitions() -> list[dict]:
    """Return tool definitions in the format expected by the LLM tool system."""
    return KUBERNETES_TOOLS
