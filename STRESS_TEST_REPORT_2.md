# Stress Test Report #2 — 2026-04-16

> Process ID Range: 143-195 (53 transactions)
> Period: 09:04:14 to 10:14:39
> Arms: ARM-01, ARM-02
> Banks: ABA, ACLEDA, WINGBANK (all same-bank transfers)

## Summary

| Metric | Value |
|--------|-------|
| Total transactions | 53 |
| Success | 49 (92.5%) |
| Stall | 2 (3.8%) |
| Failed (auto-rejected) | 2 (3.8%) |
| **Actual execution success rate** | **49/51 (96.1%)** |
| Callbacks sent | 53/53 (100%) |

## Test Phases

This test ran across two phases. A mid-test OCR fix was deployed after the first stall.

### Phase 1: PID 143-150 (8 transactions)
- 4 success, 2 stall, 2 auto-rejected
- **PID 147 (WINGBANK)**: CHECK_SCREEN failed — popup handling issue
- **PID 148 (ABA)**: OCR verification failed — Tesseract misread account `012501402` as `012801402` (`5` → `8`)
- **Root cause**: Tesseract returned first result without validating against expected value
- **Fix deployed**: OCR smart match — Tesseract now retries all preprocessing methods until expected matches, EasyOCR fallback on mismatch

### Phase 2: PID 151-195 (45 transactions)
- **45/45 success (100%)** — zero stalls after OCR fix
- OCR smart match working correctly: account/amount verified on first or subsequent Tesseract method
- Both ARMs running concurrently without camera conflicts

## Performance — Execution Duration (successful only)

| Metric | Value |
|--------|-------|
| Average | 98.7s |
| Median | 98.0s |
| Min | 88.0s |
| Max | 116.0s |
| Total successful | 49 |

### Average Duration by Bank

| Bank | Avg Duration | Count |
|------|-------------|-------|
| ABA | 98.3s | 15 |
| ACLEDA | 106.8s | 16 |
| WINGBANK | 91.8s | 18 |

### Average Duration by ARM

| ARM | Avg Duration | Count |
|-----|-------------|-------|
| ARM-01 | 99.1s | 24 |
| ARM-02 | 98.3s | 25 |

### Average Duration by ARM + Bank

| ARM / Bank | Avg Duration | Count | Success Rate |
|------------|-------------|-------|-------------|
| ARM-01/ABA | 98.0s | 8/8 | 100% |
| ARM-01/ACLEDA | 110.3s | 6/7 | 86% |
| ARM-01/WINGBANK | 93.3s | 10/12 | 83% |
| ARM-02/ABA | 98.6s | 7/8 | 88% |
| ARM-02/ACLEDA | 104.7s | 10/10 | 100% |
| ARM-02/WINGBANK | 90.0s | 8/8 | 100% |

## Stall Analysis (2 incidents)

| PID | ARM | Bank | Error |
|-----|-----|------|-------|
| 147 | ARM-01 | WINGBANK | Step execution failed |
| 148 | ARM-02 | ABA | OCR verification failed |

## Successful Transfers by Recipient

| Recipient | Account | Txns | Total Received |
|-----------|---------|------|----------------|
| Chat Channy | 008139773 | 6 | $114.26 |
| Chat Sombo | 013142782 | 6 | $89.43 |
| Doung Vivheka | 21000594130523 | 5 | $94.12 |
| Kimhout Houn | 102084337 | 8 | $147.69 |
| Lay Sav Lenh | 005155137 | 6 | $118.40 |
| Pos Vanhong | 0965944090 | 2 | $18.89 |
| Ros Vanhong | 011126831 | 4 | $63.90 |
| Sreysouna kot | 013810868 | 6 | $90.15 |
| Yee Saory | 012501402 | 6 | $98.64 |
| **Total** | | **49** | **$835.48** |

## All Transactions (53)

| PID | ARM | Bank | Amount | To Account | To Name | Status | Duration | Note |
|-----|-----|------|--------|------------|---------|--------|----------|------|
| 143 | ARM-01 | WINGBANK | $13.59 | 102084337 | Kimhout Houn | success | 100s |  |
| 144 | ARM-01 | WINGBANK | $25.54 | 102084337 | Kimhout Houn | success | 93s |  |
| 145 | ARM-01 | ABA | $23.95 | 008139773 | Chat Channy | success | 98s |  |
| 146 | ARM-01 | ACLEDA | $25.38 | 0965040668 | Chat Channy | success | 107s |  |
| 147 | ARM-01 | WINGBANK | $13.47 | 102575960 | Chat Channy | stall | 18s | Step execution failed |
| 148 | ARM-02 | ABA | $22.56 | 012501402 | Yee Saory | stall | 79s | OCR verification failed |
| 149 | ARM-01 | ACLEDA | $6.71 | 21000587530123 | Yee Saory | failed |  | auto-rejected |
| 150 | ARM-01 | WINGBANK | $14.37 | 101882950 | Yee Saory | failed |  | auto-rejected |
| 151 | ARM-02 | WINGBANK | $13.47 | 102575960 | Chat Channy | success | 96s |  |
| 152 | ARM-02 | ABA | $22.56 | 012501402 | Yee Saory | success | 99s |  |
| 153 | ARM-01 | ACLEDA | $6.71 | 21000587530123 | Yee Saory | success | 116s |  |
| 154 | ARM-02 | WINGBANK | $14.37 | 101882950 | Yee Saory | success | 90s |  |
| 155 | ARM-01 | ACLEDA | $20.73 | 21000594130523 | Doung Vivheka | success | 111s |  |
| 156 | ARM-02 | WINGBANK | $7.09 | 102084329 | Doung Vivheka | success | 89s |  |
| 157 | ARM-02 | ABA | $16.59 | 005155137 | Lay Sav Lenh | success | 99s |  |
| 158 | ARM-02 | ACLEDA | $20.84 | 21000599280723 | Lay Sav Lenh | success | 104s |  |
| 159 | ARM-02 | WINGBANK | $22.98 | 102621285 | Lay Sav Lenh | success | 88s |  |
| 160 | ARM-01 | ABA | $9.63 | 013142782 | Chat Sombo | success | 97s |  |
| 161 | ARM-02 | ACLEDA | $13.93 | 21000586189828 | Chat Sombo | success | 106s |  |
| 162 | ARM-01 | WINGBANK | $10.53 | 101853652 | Chat Sombo | success | 92s |  |
| 163 | ARM-01 | ABA | $13.35 | 011126831 | Ros Vanhong | success | 98s |  |
| 164 | ARM-02 | ACLEDA | $13.15 | 0965944090 | Pos Vanhong | success | 104s |  |
| 165 | ARM-01 | WINGBANK | $17.88 | 102602708 | Ros Vanhong | success | 93s |  |
| 166 | ARM-01 | ABA | $19.85 | 013810868 | Sreysouna kot | success | 99s |  |
| 167 | ARM-02 | ACLEDA | $11.87 | 0965066523 | Sreysouna kot | success | 103s |  |
| 168 | ARM-01 | WINGBANK | $22.57 | 102210810 | Sreysouna kot | success | 93s |  |
| 169 | ARM-01 | ABA | $16.83 | 008658930 | Kimhout Houn | success | 98s |  |
| 170 | ARM-02 | ACLEDA | $9.04 | 21000594031417 | Kimhout Houn | success | 106s |  |
| 171 | ARM-01 | WINGBANK | $17.83 | 102084337 | Kimhout Houn | success | 93s |  |
| 172 | ARM-02 | ABA | $16.31 | 008139773 | Chat Channy | success | 99s |  |
| 173 | ARM-01 | ACLEDA | $23.72 | 0965040668 | Chat Channy | success | 108s |  |
| 174 | ARM-02 | WINGBANK | $11.43 | 102575960 | Chat Channy | success | 90s |  |
| 175 | ARM-02 | ABA | $5.23 | 012501402 | Yee Saory | success | 97s |  |
| 176 | ARM-01 | ACLEDA | $28.74 | 21000587530123 | Yee Saory | success | 110s |  |
| 177 | ARM-02 | WINGBANK | $21.03 | 101882950 | Yee Saory | success | 89s |  |
| 178 | ARM-02 | ABA | $22.05 | 003121034 | Doung Vivheka | success | 98s |  |
| 179 | ARM-01 | ACLEDA | $17.81 | 21000594130523 | Doung Vivheka | success | 110s |  |
| 180 | ARM-02 | WINGBANK | $26.44 | 102084329 | Doung Vivheka | success | 89s |  |
| 181 | ARM-02 | ABA | $27.41 | 005155137 | Lay Sav Lenh | success | 99s |  |
| 182 | ARM-02 | ACLEDA | $9.71 | 21000599280723 | Lay Sav Lenh | success | 106s |  |
| 183 | ARM-02 | WINGBANK | $20.87 | 102621285 | Lay Sav Lenh | success | 89s |  |
| 184 | ARM-02 | ABA | $22.72 | 013142782 | Chat Sombo | success | 99s |  |
| 185 | ARM-02 | ACLEDA | $19.14 | 21000586189828 | Chat Sombo | success | 107s |  |
| 186 | ARM-01 | WINGBANK | $13.48 | 101853652 | Chat Sombo | success | 92s |  |
| 187 | ARM-01 | ABA | $18.68 | 011126831 | Ros Vanhong | success | 99s |  |
| 188 | ARM-02 | ACLEDA | $5.74 | 0965944090 | Pos Vanhong | success | 104s |  |
| 189 | ARM-01 | WINGBANK | $13.99 | 102602708 | Ros Vanhong | success | 92s |  |
| 190 | ARM-01 | ABA | $16.02 | 013810868 | Sreysouna kot | success | 98s |  |
| 191 | ARM-02 | ACLEDA | $10.00 | 0965066523 | Sreysouna kot | success | 99s |  |
| 192 | ARM-01 | WINGBANK | $9.84 | 102210810 | Sreysouna kot | success | 92s |  |
| 193 | ARM-01 | ABA | $26.27 | 008658930 | Kimhout Houn | success | 97s |  |
| 194 | ARM-02 | ACLEDA | $11.40 | 21000594031417 | Kimhout Houn | success | 108s |  |
| 195 | ARM-01 | WINGBANK | $27.19 | 102084337 | Kimhout Houn | success | 93s |  |
