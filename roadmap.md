# Veil — Confidential Wrapper Registry

> The home of the official Zama Wrappers Registry. Find a canonical ERC‑20 ↔ ERC‑7984 pair, wrap it, decrypt it, unwrap it — in one place every developer can point to.

**Bounty:** Zama Developer Program · Mainnet Season 3 · Bounty Track
**Target:** Confidential Wrapper Registry App
**Network:** Ethereum Sepolia (FHEVM)
**Deadline:** July 7th, 23:59 AOE (today is 2026‑06‑28 → ~9 working days)

---

## 0. Why this exists (the pitch in one paragraph)

Developers keep minting their own throwaway ERC‑20s and hand‑rolling their own
ERC‑7984 wrappers. The result is a fragmented testnet: dozens of look‑alike
"confidential USDC" tokens that don't interoperate, can't compose, and confuse
users. The **official Zama Wrappers Registry** already solves the canonical‑pair
problem onchain — but it's a raw contract, not a product. **Veil** turns that
registry into a polished, trustworthy app: browse the canonical pairs, faucet
the official cTokenMocks, wrap/unwrap with a clean async‑aware UX, and decrypt
*any* ERC‑7984 balance you own. Using the existing wrappers becomes the path of
least resistance.

**Three things that make Veil win the judging, not just pass it:**

1. **Registry-native, not registry-aware.** The onchain registry is the source
   of truth; the UI is a faithful, real‑time mirror of it (with a documented
   local‑override layer for dev pairs). We don't fork the data — we render it.
2. **Honest about FHE async.** Unwrap and decryption are not instant on FHEVM.
   Most demos hide this; Veil makes the decryption‑oracle round‑trip a
   first‑class, legible part of the UX (pending → finalizing → done).
3. **"Decrypt anything you own."** A standalone tool that decrypts the connected
   wallet's balance on *any* ERC‑7984 address — pasted or auto‑detected — even
   if it was never in the registry. This is the feature that proves we
   understand the EIP‑712 user‑decryption flow, not just the happy path.

---

## 1. Product surface (what the user sees)

```
┌───────────────────────────────────────────────────────────────┐
│  VEIL                              [Sepolia ▾]  [0xabc…ef ▾]    │
├───────────────────────────────────────────────────────────────┤
│  ┌─ Registry ─┐ ┌─ Wrap/Unwrap ─┐ ┌─ Decrypt Any ─┐ ┌─ Faucet ─┐│
│                                                                 │
│  REGISTRY  (24 pairs · onchain + 2 local)        [search 🔍]    │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ ◎ cUSDC   USD Coin Mock      6 dec   ✔ official  [Wrap →] │  │
│  │   ERC‑20  0x12..ab    ERC‑7984  0x98..cd                  │  │
│  │ ◎ cDAI    Dai Mock           18 dec  ✔ official  [Wrap →] │  │
│  │ ◎ cWETH   Wrapped Ether Mock 18 dec  ✔ official  [Wrap →] │  │
│  │ ◍ cFOO    Local Dev Token    18 dec  ⚙ local     [Wrap →] │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

Four tabs, one mental model:

| Tab | Purpose |
|-----|---------|
| **Registry** | The canonical list. Every official ERC‑20↔ERC‑7984 pair, rendered from onchain data with full metadata. Search, filter (official/local), and a one‑click jump into wrap. |
| **Wrap / Unwrap** | The conversion workbench for a selected pair. Approval → wrap → confirm; and burn → oracle‑decrypt → ERC‑20 out for unwrap. |
| **Decrypt Any** | Paste or auto‑detect any ERC‑7984 token; user‑decrypt *your* balance via EIP‑712. Works on non‑registry tokens. |
| **Faucet** | Claim the official cTokenMocks so a brand‑new wallet can try everything in 60 seconds. |

---

## 2. Architecture

```
                          ┌────────────────────────────┐
                          │        Veil Frontend        │
                          │  Next.js 14 (App Router) +   │
                          │  TypeScript + Tailwind +     │
                          │  shadcn/ui                   │
                          └──────────────┬──────────────┘
                                         │
            ┌────────────────────────────┼─────────────────────────────┐
            │                            │                             │
   ┌────────▼────────┐        ┌──────────▼──────────┐       ┌──────────▼─────────┐
   │ wagmi + viem    │        │ @zama-fhe/relayer-  │       │ TanStack Query      │
   │ wallet, reads,  │        │ sdk (FHEVM)         │       │ caching / polling   │
   │ writes, events  │        │ encrypt inputs,     │       │ for registry +      │
   │                 │        │ EIP‑712 userDecrypt │       │ oracle finalization │
   └───────┬─────────┘        └──────────┬──────────┘       └────────────────────┘
           │                             │
   ┌───────▼─────────────────────────────▼───────────────────────────────────────┐
   │                          Ethereum Sepolia (FHEVM)                             │
   │                                                                               │
   │  WrappersRegistry ──► (underlying ERC‑20, confidential ERC‑7984) tuples       │
   │  cTokenMock (ERC‑20)  ──► faucet mint()                                        │
   │  ConfidentialFungibleTokenWrapper (ERC‑7984) ──► wrap() / unwrap()            │
   │  FHEVM Decryption Oracle / KMS ──► async public decrypt (unwrap finalize)     │
   │  Relayer / Gateway ──► re‑encryption for EIP‑712 user decryption              │
   └───────────────────────────────────────────────────────────────────────────────┘
```

### Data sourcing — the hybrid model (a hard requirement)

```ts
// config/pairs.ts  — the LOCAL override layer
export const LOCAL_PAIRS: WrapperPair[] = [
  {
    source: "local",
    chainId: 11155111,
    underlying: "0xYourDevErc20...",
    confidential: "0xYourDevErc7984...",
    note: "dev-only pair, not yet registered onchain",
  },
];
```

Resolution order at runtime:

1. **Primary — onchain.** Read the `WrappersRegistry` contract on Sepolia,
   enumerate every registered pair, hydrate metadata (`name`, `symbol`,
   `decimals`, both addresses) directly from the token contracts.
2. **Augment — local config.** Merge `LOCAL_PAIRS` for custom/dev pairs not yet
   onchain. Local entries are clearly badged `⚙ local` and never masquerade as
   official.
3. **De‑dupe & verify.** If a local pair later appears onchain, the onchain
   record wins and the badge flips to `✔ official` automatically.

This is exactly the "read onchain as source of truth + local config for dev
pairs" requirement, and it doubles as our **extensibility story** (see §6).

---

## 3. The four core flows (engineering detail)

### 3.1 Browse the registry
- `readContract` against `WrappersRegistry` to get pair count + entries
  (verify the exact getter names against the deployed ABI — likely an
  enumerable list or event‑sourced index).
- Multicall token metadata (`name/symbol/decimals`) via viem `multicall` for
  speed; cache with TanStack Query (stale‑while‑revalidate).
- Render with addresses on both sides, decimals, and an explorer link.

### 3.2 Faucet (Sepolia cTokenMocks)
- Each official cTokenMock exposes a public mint/claim entrypoint (confirm the
  exact selector — commonly `mint(address,uint256)` or a parameterless
  `faucet()`). Veil calls it and shows the resulting ERC‑20 balance update.
- Per‑token "Claim" buttons in the Faucet tab; disabled if already funded above
  a threshold, with a clear cooldown/insufficient‑gas message.

### 3.3 Wrap (ERC‑20 → ERC‑7984)
```
1. Check ERC‑20 allowance(owner → wrapper)
2. If insufficient → approve(wrapper, amount)        [tx 1]
3. wrapper.wrap(to, amount)                          [tx 2]
4. Poll confidential balance handle → re-render
```
- Approval is its own state in the UI (the classic ERC‑20 two‑step). We detect
  exact‑allowance vs. infinite‑approval preference and surface it.
- After wrap, the new balance is an **encrypted handle** — we don't show a
  number until the user decrypts (one‑click into the Decrypt flow).

### 3.4 Unwrap (ERC‑7984 → ERC‑20) — the async one
```
1. Encrypt the unwrap amount client-side via relayer-sdk (createEncryptedInput)
2. Grant access / call wrapper.unwrap(from, to, encAmount, proof)
3. Contract requests PUBLIC decryption from the FHEVM oracle (async)
4. UI enters "Finalizing" — poll for the oracle callback / Unwrapped event
5. On callback → ERC‑20 transferred out → show success + new ERC‑20 balance
```
- **Key UX insight:** unwrap is *not* atomic on FHEVM — there's a decryption‑
  oracle round trip before the ERC‑20 is released. Veil models this explicitly
  with a `pending → finalizing → settled` state machine and a progress
  indicator, rather than spinning forever. This is where most submissions break;
  we make it a feature.
- Confirm the exact wrapper ABI: some versions take an encrypted `euint`, others
  take a cleartext amount with an internal access‑control / operator grant. The
  state machine adapts; the ABI is the only thing to pin down.

### 3.5 User decryption (EIP‑712) — "Decrypt Any"
```
1. Read the encrypted balance handle: erc7984.confidentialBalanceOf(user)
2. relayer-sdk: build keypair + EIP-712 typed data for user decryption
3. wallet.signTypedData(...)                          [signature, no gas]
4. relayer-sdk.userDecrypt(handles, signature, ...)
5. Display the cleartext balance, scoped to THIS wallet only
```
- Works on **any** ERC‑7984 address — pasted manually or auto‑detected by
  scanning the wallet's recent confidential‑token transfer logs.
- We validate the address actually implements the ERC‑7984 interface
  (`confidentialBalanceOf` / handle shape) before attempting, and give a precise
  error if it doesn't.
- The signed EIP‑712 grant is cached for its validity window so repeated
  decrypts don't re‑prompt the wallet.

---

## 4. Phased build plan (9‑day sprint)

| Phase | Days | Deliverable | Definition of done |
|-------|------|-------------|--------------------|
| **P0 — Spike & scaffold** | Jun 28–29 | Next.js + wagmi + relayer‑sdk boot; connect wallet on Sepolia; one successful `readContract` against the registry. | Wallet connects, network‑guard works, registry returns ≥1 pair in console. |
| **P1 — Registry read + render** | Jun 30 | Registry tab fully rendering onchain pairs + local config merge. | All official cTokenMocks visible with correct metadata; local pair badged. |
| **P2 — Faucet** | Jul 1 | Claim flow for every cTokenMock. | New wallet can fund itself; ERC‑20 balances update live. |
| **P3 — Wrap** | Jul 2 | Approval → wrap → encrypted handle. | A faucet token wraps successfully; tx links shown. |
| **P4 — User decryption** | Jul 3 | EIP‑712 userDecrypt for registry + arbitrary tokens. | Wrapped balance decrypts; pasted external ERC‑7984 decrypts. |
| **P5 — Unwrap (async)** | Jul 4 | Unwrap state machine incl. oracle finalize. | Confidential → ERC‑20 round trip completes end‑to‑end. |
| **P6 — Error handling & polish** | Jul 5 | All edge cases (§5), responsive UI, empty/loading states. | Every failure mode shows a human message, never a raw revert. |
| **P7 — Deploy + README + demo + X** | Jul 6 | Vercel live URL, README, 3‑min video, X thread. | Judge can do every flow on the live URL; submission package complete. |
| **Buffer** | Jul 7 | Bug bash + resubmit safety margin. | — |

> Order rationale: decryption (P4) lands **before** unwrap (P5) because unwrap's
> "finalizing" UX reuses the same async‑polling infrastructure, and because a
> wrapped balance is useless to demo until you can read it.

---

## 5. Sensible error handling (explicit requirement)

| Condition | Detection | UX response |
|-----------|-----------|-------------|
| Wrong network | `chainId !== 11155111` | Blocking banner + one‑click "Switch to Sepolia". |
| Missing/low approval | `allowance < amount` | Inline "Approve first" step; never let wrap revert. |
| Insufficient ERC‑20 balance | `balanceOf < amount` | Disable wrap, link to Faucet tab. |
| Insufficient confidential balance | post‑decrypt compare | Cap unwrap input at decrypted max. |
| Unsupported / non‑ERC‑7984 address | interface probe fails | "This address isn't an ERC‑7984 token." |
| Oracle finalization stalls | timeout on poll | "Still finalizing onchain — safe to wait or check explorer," with tx link. |
| User rejects signature/tx | wallet error code | Soft toast, restore prior state, no dead spinner. |
| Out of gas / RPC flake | viem error class | Retry affordance + raw error behind a "details" disclosure. |

Principle: **a judge should never see an unparsed revert string.** Every error
maps to a sentence a non‑expert understands.

---

## 6. Extensibility — adding a new pair (documented requirement)

Two supported, documented paths in the README:

**A) Local dev pair (instant, no onchain registration):**
```ts
// config/pairs.ts
LOCAL_PAIRS.push({
  source: "local",
  chainId: 11155111,
  underlying: "0xMyToken",
  confidential: "0xMyConfidentialWrapper",
  note: "my hackathon token",
});
```
Save → it appears in the Registry tab badged `⚙ local`, fully wrap/unwrap/
decrypt‑able. Worked example included in README with screenshots.

**B) Canonical onchain pair (the real path):**
Register the pair in the official `WrappersRegistry` contract (link to Zama's
registration process/script). On the next refresh Veil reads it as `✔ official`
with **zero app code changes** — that's the whole point of being registry‑native.

The README spells out both with copy‑paste examples and explains *when* to use
which.

---

## 7. Requirements traceability — how every requirement is fulfilled

| # | Requirement (from `bounty_requirements.md`) | How Veil fulfills it | Where |
|---|---------------------------------------------|----------------------|-------|
| R1 | Web dApp with public live URL, every feature usable | Next.js app on Vercel; wallet connect on Sepolia; all four tabs functional | §1, P7 |
| R2 | Support Sepolia; shield/unshield/decrypt work | Sepolia‑only network guard; wrap (shield), unwrap (unshield), userDecrypt all implemented | §3, P3–P5 |
| R3 | Hybrid registry: onchain primary + local config | Resolution order: onchain truth → merge `LOCAL_PAIRS` → de‑dupe | §2 "hybrid model" |
| R4 | Include every official cTokenMock in Sepolia registry | Driven by onchain enumeration → all official mocks surface automatically; coverage test asserts each docs‑listed mock is present | §3.1, P1 |
| R5 | Wrap + unwrap for every registry pair | Generic wrap/unwrap workbench keyed by pair, not hardcoded per token | §3.3–3.4 |
| R6 | User‑decrypt any ERC‑7984 (paste or auto‑detect), not just registered | "Decrypt Any" tab: paste address + log‑scan auto‑detect + interface probe | §3.5 |
| R7 | Documented process to add a new pair (with example) | Two paths (local + onchain), worked examples in README | §6 |
| R8 | Open source, public GitHub repo | MIT‑licensed public repo, conventional commits, CI lint/typecheck | §8 |
| T1 | Read onchain registry + render metadata (symbol/decimals/name/addresses both nets) | Multicall metadata hydration, both‑address display | §3.1 |
| T2 | Faucet interaction with official cTokenMocks | Per‑token claim flow | §3.2 |
| T3 | Wrap flow: approval → wrap → confirmation | Two‑step approval state machine + confirm | §3.3 |
| T4 | Unwrap flow with correct allowance/access‑control | Encrypted input + operator/access grant + oracle finalize | §3.4 |
| T5 | EIP‑712 user‑decryption of own balances on any ERC‑7984 | relayer‑sdk keypair + signTypedData + userDecrypt | §3.5 |
| T6 | Frontend integration with FHEVM relayer SDK / fhevmjs | `@zama-fhe/relayer-sdk` for encrypt inputs + user decryption | §2 |
| T7 | Error handling: approvals, balance, network, unsupported tokens | Full error matrix | §5 |
| S1 | GitHub repo with full source + README (URL, networks, sourcing, add‑pair, deploy scripts) | README sections mirror this roadmap | §8 |
| S2 | Live deployment, every feature on Sepolia | Vercel live URL | P7 |
| S3 | 3‑min real‑person demo video covering the full script | Demo script in §9 | §9 |
| S4 | X thread/article introducing the project | Thread outline in §9 | §9 |
| J‑Coverage | All official Sepolia cTokenMocks surfaced & working | R4 + automated coverage assertion | §3.1 |
| J‑Correctness | wrap/unwrap/decrypt correct onchain; EIP‑712 correct | End‑to‑end tested on Sepolia | P3–P5 |
| J‑Extensibility | Clean, documented add‑pair path | §6 |
| J‑UX | Approvals, network switch, errors handled gracefully | §5 + async state machines |
| J‑CodeQuality | Clean, typed, documented | §8 |
| J‑Production | Stable live deployment, trustworthy | §8 hardening |

---

## 8. Code quality & production‑readiness

- **TypeScript strict**, ESLint + Prettier, Husky pre‑commit.
- **Typed contracts:** generate ABIs/types (wagmi CLI / abitype) so contract
  calls are compile‑time checked.
- **Centralized config:** one `chains.ts` / `contracts.ts` with all Sepolia
  addresses, each annotated with its docs source — **single place to update if
  Zama redeploys.**
- **Resilience:** RPC fallback (public + a keyed provider), query retries,
  optimistic‑but‑honest UI (never claim success before confirmation).
- **Tests:** unit tests for the pair‑resolution/merge logic and the unwrap state
  machine; a Sepolia integration smoke test for the full wrap→decrypt→unwrap
  loop.
- **Accessibility & responsive:** keyboard‑navigable, mobile‑legible.
- **No secrets in repo:** `.env.example` documents required RPC keys / WalletConnect ID.

**⚠️ Must‑verify‑against‑live‑docs before submission (do not trust hardcoded values):**
- `WrappersRegistry` Sepolia address + exact getter/enumeration ABI.
- Each official cTokenMock address + faucet selector.
- `ConfidentialFungibleTokenWrapper` `wrap`/`unwrap` signatures (encrypted vs.
  cleartext amount; operator/access‑control requirements).
- relayer‑sdk package name/version + initialization (WASM/network config) and
  the current user‑decryption API surface.
- Decryption‑oracle callback shape / event used to detect unwrap finalization.

---

## 9. Submission package (non‑code deliverables)

**README outline** (required content): live URL · supported networks · how the
registry is sourced (hybrid model) · how to add a pair (both paths, with
example) · deployment scripts · local dev setup · architecture diagram.

**3‑minute video script** (real person, no AI voice/video):
1. (0:00–0:20) The problem: ecosystem fragmentation, look‑alike confidential tokens.
2. (0:20–0:40) Browse the registry — official pairs from onchain.
3. (0:40–1:00) Claim a cTokenMock from the faucet.
4. (1:00–1:30) Wrap the mock → encrypted balance.
5. (1:30–1:55) Decrypt the resulting ERC‑7984 balance (EIP‑712).
6. (1:55–2:20) Unwrap back to ERC‑20 (show the async finalize honestly).
7. (2:20–2:40) Decrypt an **arbitrary** off‑registry ERC‑7984 token.
8. (2:40–3:00) How to add a new pair + closing.

**X thread outline:** hook (fragmentation problem) → what Veil is → GIF of the
wrap→decrypt loop → the "decrypt anything you own" feature → registry‑native
extensibility → live URL + repo + video link.

---

## 10. Stretch goals (only if buffer survives)

- **Pair detail pages** with shareable deep links (`/pair/cUSDC`).
- **Activity feed** of recent wraps/unwraps from contract events.
- **"Add pair" PR helper:** a form that generates the `config/pairs.ts` diff and
  opens a pre‑filled GitHub PR — turns extensibility into one click.
- **Batch decrypt** across all your confidential balances in one signature.
- **Light/dark themes** + a polished empty‑wallet onboarding.

---

### Definition of "done" for the whole bounty
A judge opens the live URL on a fresh wallet, switches to Sepolia, faucets a
cTokenMock, wraps it, decrypts the confidential balance, unwraps it back,
decrypts an unrelated ERC‑7984 token, and reads in the README exactly how to add
a new pair — all without hitting a single raw revert or dead spinner.
