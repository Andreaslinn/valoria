# Layer only the shared-engine integration over the verified Oracle API image.
# Before building, verify this local tag resolves to:
# sha256:70447ccad59a69df70c52a1ee90cac8f3f92d98dff818c48c02abf24fec3297d
FROM valoria-remediation:candidate-20261012-v6
COPY services/radar.py /app/services/radar.py
COPY api/deps.py /app/api/deps.py
COPY api/v1/radar.py /app/api/v1/radar.py
