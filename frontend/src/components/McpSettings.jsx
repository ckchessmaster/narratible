import { useEffect, useState } from 'react'
import {
  getMcpStatus,
  toggleMcp,
  getMcpTokens,
  createMcpToken,
  deleteMcpToken,
} from '../api'

export default function McpSettings({ toast }) {
  const [status, setStatus] = useState(null)
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [tokenName, setTokenName] = useState('')
  const [creatingToken, setCreatingToken] = useState(false)
  const [newlyCreatedSecret, setNewlyCreatedSecret] = useState(null)
  const [configClient, setConfigClient] = useState('vscode_http')
  const [copiedKey, setCopiedKey] = useState('')

  const loadData = async () => {
    try {
      setLoading(true)
      const [statusRes, tokensRes] = await Promise.all([
        getMcpStatus(),
        getMcpTokens(),
      ])
      setStatus(statusRes)
      setTokens(tokensRes)
    } catch (err) {
      if (toast) toast('Failed to load MCP status: ' + err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleToggle = async (e) => {
    const nextVal = e.target.checked
    try {
      setToggling(true)
      const res = await toggleMcp(nextVal)
      setStatus(prev => ({ ...prev, enabled: res.enabled }))
      if (toast) toast(res.enabled ? 'MCP server enabled.' : 'MCP server disabled.', 'info')
    } catch (err) {
      if (toast) toast('Failed to toggle MCP: ' + err.message, 'error')
    } finally {
      setToggling(false)
    }
  }

  const handleCreateToken = async (e) => {
    e.preventDefault()
    if (!tokenName.trim()) return
    try {
      setCreatingToken(true)
      const res = await createMcpToken(tokenName.trim())
      setNewlyCreatedSecret(res)
      setTokenName('')
      setTokens(prev => [...prev, res.token])
      setStatus(prev => ({ ...prev, token_count: (prev?.token_count || 0) + 1 }))
      if (toast) toast('Token created successfully. Be sure to copy it now!', 'success')
    } catch (err) {
      if (toast) toast('Failed to create token: ' + err.message, 'error')
    } finally {
      setCreatingToken(false)
    }
  }

  const handleRevokeToken = async (tokenId, name) => {
    if (!window.confirm(`Are you sure you want to revoke the token "${name}"? External apps using this token will lose access.`)) {
      return
    }
    try {
      await deleteMcpToken(tokenId)
      setTokens(prev => prev.filter(t => t.id !== tokenId))
      setStatus(prev => ({ ...prev, token_count: Math.max(0, (prev?.token_count || 1) - 1) }))
      if (toast) toast('Token revoked.', 'info')
    } catch (err) {
      if (toast) toast('Failed to revoke token: ' + err.message, 'error')
    }
  }

  const copyToClipboard = (text, key) => {
    navigator.clipboard.writeText(text)
    setCopiedKey(key)
    setTimeout(() => setCopiedKey(''), 2500)
    if (toast) toast('Copied to clipboard!', 'success')
  }

  const activeTokenSecret = newlyCreatedSecret?.secret || '<YOUR_PAT_TOKEN>'

  const getClientConfigSnippet = () => {
    const httpEndpoint = status?.http_url || 'http://localhost:8000/mcp'
    if (configClient === 'vscode_http') {
      return JSON.stringify(
        {
          servers: {
            narratible: {
              type: "http",
              url: httpEndpoint,
              headers: {
                Authorization: `Bearer ${activeTokenSecret}`,
              },
            },
          },
        },
        null,
        2
      )
    }
    if (configClient === 'claude_desktop_http') {
      return JSON.stringify(
        {
          mcpServers: {
            narratible: {
              url: httpEndpoint,
              headers: {
                Authorization: `Bearer ${activeTokenSecret}`,
              },
            },
          },
        },
        null,
        2
      )
    }
    if (configClient === 'cursor') {
      return JSON.stringify(
        {
          mcpServers: {
            narratible: {
              url: httpEndpoint,
              headers: {
                Authorization: `Bearer ${activeTokenSecret}`,
              },
            },
          },
        },
        null,
        2
      )
    }
    return ''
  }

  if (loading) {
    return <div className="text-muted text-sm p-4">Loading MCP server status…</div>
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ── Master Enable/Disable Card ──────────────────────────────── */}
      <div
        className="glass p-4 flex items-center justify-between gap-4"
        style={{ borderRadius: 'var(--radius-sm)' }}
      >
        <div style={{ flex: 1 }}>
          <div className="flex items-center gap-2 mb-1">
            <span style={{ fontWeight: 600, fontSize: 15 }}>Model Context Protocol (MCP) Server</span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                padding: '2px 7px',
                borderRadius: 99,
                background: status?.enabled ? 'rgba(34,197,94,0.18)' : 'rgba(156,163,175,0.18)',
                color: status?.enabled ? 'var(--success, #22c55e)' : 'var(--text-muted)',
                border: status?.enabled
                  ? '1px solid rgba(34,197,94,0.35)'
                  : '1px solid rgba(156,163,175,0.35)',
              }}
            >
              {status?.enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          <div className="text-xs text-muted" style={{ lineHeight: 1.5 }}>
            Exposes local Narratible tools (projects, tasks, chapter editing, TTS generation, logs)
            to external AI assistants like Claude Desktop, Cursor, and VS Code.
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <div className="toggle-switch">
            <input
              type="checkbox"
              checked={status?.enabled || false}
              disabled={toggling}
              onChange={handleToggle}
            />
            <span className="toggle-slider"></span>
          </div>
        </label>
      </div>

      {/* ── Endpoints Overview ────────────────────────────────────────── */}
      <div
        className="glass p-3 flex flex-col gap-2"
        style={{ borderRadius: 'var(--radius-sm)', background: 'rgba(255,255,255,0.02)' }}
      >
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted">Streamable HTTP Endpoint:</span>
          <div className="flex items-center gap-2 font-mono">
            <code style={{ background: 'rgba(0,0,0,0.2)', padding: '2px 6px', borderRadius: 4 }}>
              {status?.http_url || 'http://localhost:8000/mcp'}
            </code>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => copyToClipboard(status?.http_url || 'http://localhost:8000/mcp', 'http_url')}
            >
              {copiedKey === 'http_url' ? '✓ Copied' : 'Copy'}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="text-muted">Stdio CLI Command:</span>
          <div className="flex items-center gap-2 font-mono">
            <code style={{ background: 'rgba(0,0,0,0.2)', padding: '2px 6px', borderRadius: 4 }}>
              {status?.stdio_command || 'narratible --mcp-stdio'}
            </code>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => copyToClipboard(status?.stdio_command || 'narratible --mcp-stdio', 'stdio_cmd')}
            >
              {copiedKey === 'stdio_cmd' ? '✓ Copied' : 'Copy'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Newly Created Secret Notification ─────────────────────────── */}
      {newlyCreatedSecret && (
        <div
          className="p-3 flex flex-col gap-2"
          style={{
            borderRadius: 'var(--radius-sm)',
            background: 'rgba(34,197,94,0.08)',
            border: '1px solid rgba(34,197,94,0.4)',
          }}
        >
          <div className="flex items-center justify-between">
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--success, #22c55e)' }}>
              🔑 Personal Access Token Created ({newlyCreatedSecret.token.name})
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => setNewlyCreatedSecret(null)}
            >
              Dismiss
            </button>
          </div>
          <div className="text-xs text-muted">
            Make sure to copy your Personal Access Token now. For your security, you will not be able to see it again!
          </div>
          <div className="flex items-center gap-2 mt-1">
            <input
              type="text"
              readOnly
              value={newlyCreatedSecret.secret}
              className="font-mono text-xs"
              style={{
                flex: 1,
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid rgba(34,197,94,0.3)',
                padding: '6px 10px',
                borderRadius: 4,
                color: '#fff',
              }}
              onFocus={e => e.target.select()}
            />
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => copyToClipboard(newlyCreatedSecret.secret, 'new_secret')}
            >
              {copiedKey === 'new_secret' ? '✓ Copied' : 'Copy Token'}
            </button>
          </div>
        </div>
      )}

      {/* ── Personal Access Tokens Management ─────────────────────────── */}
      <div>
        <div className="section-title mb-2">Personal Access Tokens (PAT)</div>
        <div className="text-xs text-muted mb-3">
          Required for HTTP / SSE connections to the MCP endpoint. Local stdio commands run under local OS user permissions.
        </div>

        {/* Create Token Form */}
        <form onSubmit={handleCreateToken} className="flex gap-2 mb-3">
          <input
            type="text"
            placeholder="Token name (e.g. Claude Desktop, Cursor, Agent 1)"
            value={tokenName}
            onChange={e => setTokenName(e.target.value)}
            disabled={creatingToken}
            style={{ flex: 1 }}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={creatingToken || !tokenName.trim()}
          >
            {creatingToken ? 'Generating…' : '+ Generate Token'}
          </button>
        </form>

        {/* Tokens List */}
        {tokens.length === 0 ? (
          <div
            className="glass p-3 text-xs text-muted text-center"
            style={{ borderRadius: 'var(--radius-sm)' }}
          >
            No access tokens generated yet. Generate a token to connect remote or browser/HTTP clients.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {tokens.map(token => (
              <div
                key={token.id}
                className="glass p-3 flex items-center justify-between gap-3"
                style={{ borderRadius: 'var(--radius-sm)' }}
              >
                <div style={{ flex: 1 }}>
                  <div className="flex items-center gap-2">
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{token.name}</span>
                    <code className="text-xs text-muted font-mono" style={{ opacity: 0.8 }}>
                      {token.prefix}
                    </code>
                  </div>
                  <div className="text-xs text-muted mt-0.5">
                    Created {new Date(token.created_at).toLocaleDateString()}
                    {token.last_used_at
                      ? ` · Last used ${new Date(token.last_used_at).toLocaleDateString()}`
                      : ' · Never used'}
                  </div>
                </div>

                <button
                  type="button"
                  className="btn btn-ghost btn-xs text-danger"
                  style={{ color: 'var(--danger, #ef4444)' }}
                  onClick={() => handleRevokeToken(token.id, token.name)}
                >
                  Revoke
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── One-Click Client Configuration ────────────────────────────── */}
      <div className="mt-2">
        <div className="section-title mb-2">Connect Your AI Assistant</div>
        <div className="text-xs text-muted mb-3">
          Select your tool below and copy the pre-configured JSON snippet directly into your client config.
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          {[
            { id: 'vscode_http', label: 'VS Code (HTTP)' },
            { id: 'claude_desktop_http', label: 'Claude Desktop (HTTP)' },
            { id: 'cursor', label: 'Cursor (HTTP)' },
          ].map(client => (
            <button
              key={client.id}
              type="button"
              className="btn btn-xs"
              style={{
                borderRadius: 14,
                padding: '4px 12px',
                background: configClient === client.id ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)',
                color: configClient === client.id ? '#fff' : 'var(--text-secondary)',
                border: '1px solid var(--glass-border)',
              }}
              onClick={() => setConfigClient(client.id)}
            >
              {client.label}
            </button>
          ))}
        </div>

        <div style={{ position: 'relative' }}>
          <pre
            className="p-3 text-xs font-mono"
            style={{
              background: 'rgba(0,0,0,0.4)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--glass-border)',
              overflowX: 'auto',
              maxHeight: 180,
            }}
          >
            {getClientConfigSnippet()}
          </pre>
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              background: 'rgba(30,30,46,0.85)',
            }}
            onClick={() => copyToClipboard(getClientConfigSnippet(), 'client_config')}
          >
            {copiedKey === 'client_config' ? '✓ Copied' : 'Copy JSON'}
          </button>
        </div>
      </div>
    </div>
  )
}
