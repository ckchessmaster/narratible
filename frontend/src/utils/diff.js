/**
 * Tokenize text into words, punctuation, and whitespace sequences.
 * Separating punctuation ensures attached commas/quotes don't invalidate word equality.
 */
function tokenize(text) {
  if (!text) return []
  // Matches unicode word tokens, individual punctuation symbols, or whitespace runs
  const tokenRegex = /([\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]+|\s+)/gu
  return text.match(tokenRegex) || []
}

/**
 * Myers Diff Algorithm (SES - Shortest Edit Script) with prefix/suffix pruning.
 * Computes optimal token-level diff in O((N + M) * D) time and O(N + M) memory.
 */
function myersDiff(a, b) {
  const n = a.length
  const m = b.length
  if (n === 0 && m === 0) return []
  if (n === 0) return b.map(text => ({ type: 'insert', text }))
  if (m === 0) return a.map(text => ({ type: 'delete', text }))

  // 1. Fast path: common prefix
  let prefix = 0
  while (prefix < n && prefix < m && a[prefix] === b[prefix]) {
    prefix++
  }

  // 2. Fast path: common suffix
  let suffix = 0
  while (suffix < (n - prefix) && suffix < (m - prefix) && a[n - 1 - suffix] === b[m - 1 - suffix]) {
    suffix++
  }

  const aMid = a.slice(prefix, n - suffix)
  const bMid = b.slice(prefix, m - suffix)
  const midN = aMid.length
  const midM = bMid.length

  let midOps = []
  if (midN === 0 && midM === 0) {
    midOps = []
  } else if (midN === 0) {
    midOps = bMid.map(text => ({ type: 'insert', text }))
  } else if (midM === 0) {
    midOps = aMid.map(text => ({ type: 'delete', text }))
  } else {
    // Myers SES on the remaining middle slice
    const offset = midN + midM
    const maxD = Math.min(offset, 2500)
    const v = new Int32Array(2 * offset + 1)
    const trace = []
    let found = false
    let finalD = 0

    outer:
    for (let d = 0; d <= maxD; d++) {
      finalD = d
      trace.push(new Int32Array(v))

      for (let k = -d; k <= d; k += 2) {
        let x
        if (k === -d || (k !== d && v[k - 1 + offset] < v[k + 1 + offset])) {
          x = v[k + 1 + offset]
        } else {
          x = v[k - 1 + offset] + 1
        }
        let y = x - k

        while (x < midN && y < midM && aMid[x] === bMid[y]) {
          x++
          y++
        }
        v[k + offset] = x

        if (x >= midN && y >= midM) {
          found = true
          break outer
        }
      }
    }

    if (found) {
      let x = midN
      let y = midM
      for (let d = finalD; d > 0; d--) {
        const vPrev = trace[d]
        const k = x - y
        let prevK
        if (k === -d || (k !== d && vPrev[k - 1 + offset] < vPrev[k + 1 + offset])) {
          prevK = k + 1
        } else {
          prevK = k - 1
        }
        const prevX = vPrev[prevK + offset]
        const prevY = prevX - prevK

        while (x > prevX && y > prevY) {
          midOps.push({ type: 'equal', text: aMid[x - 1] })
          x--
          y--
        }
        if (d > 0) {
          if (x === prevX) {
            midOps.push({ type: 'insert', text: bMid[prevY] })
            y--
          } else {
            midOps.push({ type: 'delete', text: aMid[prevX] })
            x--
          }
        }
      }
      while (x > 0 && y > 0) {
        midOps.push({ type: 'equal', text: aMid[x - 1] })
        x--
        y--
      }
      midOps.reverse()
    } else {
      // Coarse fallback if max edit depth was exceeded
      midOps = [
        ...aMid.map(text => ({ type: 'delete', text })),
        ...bMid.map(text => ({ type: 'insert', text })),
      ]
    }
  }

  // Combine prefix + middle operations + suffix
  const ops = []
  for (let i = 0; i < prefix; i++) {
    ops.push({ type: 'equal', text: a[i] })
  }
  for (const op of midOps) {
    ops.push(op)
  }
  for (let i = n - suffix; i < n; i++) {
    ops.push({ type: 'equal', text: a[i] })
  }
  return ops
}

/**
 * Word-level diff computation based on Myers SES with punctuation separation
 * and contiguous operation coalescing.
 *
 * @param {string} oldText
 * @param {string} newText
 * @returns {Array<{ type: 'equal' | 'delete' | 'insert', text: string }>}
 */
export function computeWordDiff(oldText = '', newText = '') {
  if (oldText === newText) {
    return [{ type: 'equal', text: oldText }]
  }
  if (!oldText) {
    return [{ type: 'insert', text: newText }]
  }
  if (!newText) {
    return [{ type: 'delete', text: oldText }]
  }

  const oldTokens = tokenize(oldText)
  const newTokens = tokenize(newText)

  const rawOps = myersDiff(oldTokens, newTokens)

  // Merge contiguous segments of the same operation type
  const merged = []
  for (const op of rawOps) {
    if (merged.length > 0 && merged[merged.length - 1].type === op.type) {
      merged[merged.length - 1].text += op.text
    } else {
      merged.push({ type: op.type, text: op.text })
    }
  }

  return merged
}
