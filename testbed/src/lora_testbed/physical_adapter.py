"""One physical request/cleanup policy bound to a particular USB connection.

NodeSession still owns typed wire validation, serialization, keys and port I/O.
This adapter never connects, claims, resumes or substitutes a different node.
"""


class PhysicalAdapter:
    def __init__(self, nodes):
        self.nodes = nodes

    def bind(self, role):
        node = self.nodes[role]
        if not node.connected or node.identity is None or node.connection_id is None:
            raise ValueError(f"Node {role} needs a fresh physical connection")
        return {
            "role": role,
            "device_id": node.identity.device_id,
            "boot_id": node.identity.boot_id,
            "connection_id": node.connection_id,
        }

    def current(self, binding):
        node = self.nodes[binding["role"]]
        if (
            not node.connected
            or node.identity is None
            or node.connection_id != binding["connection_id"]
            or (node.identity.device_id, node.identity.boot_id)
            != (binding["device_id"], binding["boot_id"])
        ):
            raise ValueError(
                f"Node {binding['role']} connection/device/boot changed; reconnect and start fresh"
            )
        return node

    async def request(self, binding, name, args=None, **options):
        node = self.current(binding)
        result = await node.request(name, args, **options)
        self.current(binding)  # A reply cannot authorize work across a reconnect.
        return result

    async def cleanup(
        self, binding, *, run_id=None, operation_id=None, local_work=False, on_record=None
    ):
        result = {"confirmed": False, "error": None, "errors": [], "steps": []}

        def trace(value):
            if on_record:
                try:
                    on_record(value)
                except (OSError, ValueError) as exc:
                    result["errors"].append({"command": "evidence", "error": str(exc)})

        async def attempt(name, args=None, **kwargs):
            try:
                return await self.request(
                    binding, name, args, on_record=trace, timeout=0.75, retries=0, **kwargs
                )
            except (OSError, ValueError, TimeoutError) as exc:
                result["errors"].append({"command": name, "error": str(exc)})
                return None

        foreign = False
        try:
            node = self.current(binding)
            if run_id:
                if node.rf_run_id not in (None, run_id):
                    foreign = True
                    raise ValueError("Another RF run owns this connection")
                if node.rf_run_id == run_id:
                    stopped = await attempt("run.stop", {"reason": "host_shutdown"}, run_id=run_id)
                    if stopped is not None:
                        result["steps"].append("run stopped")
                    closed = await attempt("session.close", run_id=run_id)
                    if closed is not None:
                        result["steps"].append("session closed")
            status = await attempt("status.get")
            if status and (operation_id or local_work) and status["operation_id"]:
                if operation_id and status["operation_id"] != operation_id:
                    foreign = True
                    raise ValueError("Another local operation owns this connection")
                stopped = await attempt("operation.stop", {"operation_id": status["operation_id"]})
                if stopped is not None:
                    result["steps"].append("operation stopped")
                status = await attempt("status.get")
            if (
                not status
                or status["state"] != "idle"
                or status["run_id"] is not None
                or status["security_ready"]
            ):
                raise ValueError("Node did not confirm idle with no active run or keys")
            result["steps"].append("idle confirmed")
            result["confirmed"] = True
        except (OSError, ValueError, TimeoutError) as exc:
            result["error"] = str(exc)
            # Retire uncertain ownership only on this exact connection, never a replacement.
            try:
                node = self.current(binding)
            except ValueError:
                pass
            else:
                if not foreign:
                    await node.close(release=False)
                    result["steps"].append("uncertain ownership disconnected")
        return result
