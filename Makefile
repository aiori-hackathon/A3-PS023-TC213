.PHONY: all test demo audit clean

VENV = .venv/bin

all: test

test:
	$(VENV)/pytest -v

demo:
	./scripts/run_demo.sh

audit:
	./scripts/leak_check.sh

clean:
	-pkill -9 -f "[u]vicorn controller.server:app"
	-pkill -9 -f "[u]vicorn worker.agent:app"
	-killall -9 cloud-hypervisor 2>/dev/null || true
	-fuser -k 8000/tcp 8001/tcp 8002/tcp 2>/dev/null || true
	rm -f /tmp/ch_sockets/*.sock /tmp/ch_sockets/*_overlay.qcow2
	rm -f data/cluster_state.db data/cluster_state.db-wal data/cluster_state.db-shm
	@echo "[*] Cleaned all cluster processes, sockets, and ephemeral state."
