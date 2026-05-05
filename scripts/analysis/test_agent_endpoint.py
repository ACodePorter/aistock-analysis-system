import time, json, sys, requests

BASE = "http://localhost:8081"

def main():
    strict = len(sys.argv) > 1 and sys.argv[1] == "--strict"
    r = requests.post(f"{BASE}/api/agent/run", params={"strict_json": str(strict).lower()})
    r.raise_for_status()
    job = r.json()
    job_id = job['job_id']
    print("Launched job", job)
    for i in range(60):
        s = requests.get(f"{BASE}/api/agent/status/{job_id}")
        if s.status_code == 404:
            print("Job disappeared")
            return
        info = s.json()
        print("[poll]", i, info['status'])
        if info['status'] != 'running':
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return
        time.sleep(2)
    print("Timeout waiting for job finish")

if __name__ == "__main__":
    main()
