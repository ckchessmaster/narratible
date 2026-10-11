import { useState, useRef, useEffect } from 'react'
import { X, Upload, Trash2, Check, BookOpen } from 'lucide-react'
import { updateProject, uploadCover } from '../api'

export default function BookDetailsModal({
  projectId,
  meta,
  isOpen,
  onClose,
  onUpdateMeta,
  toast,
}) {
  const [formData, setFormData] = useState({
    title: '',
    author: '',
    language: 'en',
    description: '',
    publisher: '',
    subject: '',
    isbn: '',
    series: '',
    cover_image: null,
  })
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [coverVersion, setCoverVersion] = useState(0)
  const fileInputRef = useRef(null)

  useEffect(() => {
    if (meta) {
      /* eslint-disable react-hooks/set-state-in-effect */
      setFormData({
        title: meta.title || '',
        author: meta.author || '',
        language: meta.language || 'en',
        description: meta.description || '',
        publisher: meta.publisher || '',
        subject: meta.subject || '',
        isbn: meta.isbn || '',
        series: meta.series || '',
        cover_image: meta.cover_image || null,
      })
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [meta])

  if (!isOpen) return null

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  const handleSave = async (customData = null) => {
    const dataToSave = customData || formData
    if (!projectId) return
    setSaving(true)
    try {
      await updateProject(projectId, dataToSave)
      if (onUpdateMeta) {
        onUpdateMeta(dataToSave)
      }
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err) {
      if (toast) toast(err.message || 'Failed to save book details', 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleCoverUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await uploadCover(projectId, file)
      const updatedCover = res.cover_image
      setFormData(prev => ({ ...prev, cover_image: updatedCover }))
      setCoverVersion(Date.now())
      if (onUpdateMeta) onUpdateMeta({ cover_image: updatedCover })
      if (toast) toast('Cover uploaded successfully', 'success')
    } catch (err) {
      if (toast) toast(err.message || 'Failed to upload cover', 'error')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleRemoveCover = async () => {
    const updated = { ...formData, cover_image: null }
    setFormData(updated)
    await handleSave(updated)
    if (toast) toast('Cover image removed', 'info')
  }

  return (
    <div className="drawer-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title-group">
            <h2 className="drawer-title">Book Details</h2>
            <span className="drawer-subtitle">Global metadata embedded into EPUB and audiobook exports</span>
          </div>
          <button className="btn-icon" onClick={onClose} aria-label="Close Book Details">
            <X size={20} />
          </button>
        </div>

        <div className="drawer-body">
          {/* Cover Art Section */}
          <div className="book-cover-section">
            <div className="book-cover-preview">
              {formData.cover_image ? (
                <img
                  src={`/api/projects/${projectId}/cover?v=${coverVersion}`}
                  alt="Book Cover"
                  className="book-cover-img"
                  onError={(e) => {
                    e.target.style.display = 'none'
                  }}
                />
              ) : (
                <div className="book-cover-placeholder">
                  <BookOpen size={36} className="text-muted" />
                  <span className="text-xs text-muted mt-2">No Cover</span>
                </div>
              )}
            </div>
            <div className="book-cover-controls">
              <input
                ref={fileInputRef}
                type="file"
                accept=".jpg,.jpeg,.png"
                style={{ display: 'none' }}
                onChange={handleCoverUpload}
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={14} className="mr-1" />
                {formData.cover_image ? 'Replace Cover' : 'Upload Cover'}
              </button>
              {formData.cover_image && (
                <button
                  type="button"
                  className="btn btn-danger-ghost btn-sm"
                  onClick={handleRemoveCover}
                >
                  <Trash2 size={14} className="mr-1" />
                  Remove
                </button>
              )}
              <span className="text-xs text-muted">Supports JPG, PNG up to 10MB</span>
            </div>
          </div>

          {/* Metadata Fields */}
          <div className="form-group">
            <label className="form-label" htmlFor="book-title">Title</label>
            <input
              id="book-title"
              type="text"
              className="form-input"
              value={formData.title}
              onChange={e => handleChange('title', e.target.value)}
              onBlur={() => handleSave()}
              placeholder="e.g. The War of the Worlds"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="book-author">Author</label>
            <input
              id="book-author"
              type="text"
              className="form-input"
              value={formData.author}
              onChange={e => handleChange('author', e.target.value)}
              onBlur={() => handleSave()}
              placeholder="e.g. H. G. Wells"
            />
          </div>

          <div className="form-row-2">
            <div className="form-group" data-tip-anchor="metadata-language">
              <label className="form-label" htmlFor="book-language">Language</label>
              <select
                id="book-language"
                className="form-select"
                value={formData.language}
                onChange={e => { handleChange('language', e.target.value); handleSave({ ...formData, language: e.target.value }); }}
              >
                <option value="en">English (en)</option>
                <option value="es">Spanish (es)</option>
                <option value="fr">French (fr)</option>
                <option value="de">German (de)</option>
                <option value="it">Italian (it)</option>
                <option value="pt">Portuguese (pt)</option>
                <option value="ja">Japanese (ja)</option>
                <option value="zh">Chinese (zh)</option>
              </select>
            </div>

            <div className="form-group" data-tip-anchor="metadata-isbn">
              <label className="form-label" htmlFor="book-isbn">ISBN</label>
              <input
                id="book-isbn"
                type="text"
                className="form-input"
                value={formData.isbn}
                onChange={e => handleChange('isbn', e.target.value)}
                onBlur={() => handleSave()}
                placeholder="e.g. 978-0141441146"
              />
            </div>
          </div>

          <div className="form-row-2">
            <div className="form-group">
              <label className="form-label" htmlFor="book-series">Series</label>
              <input
                id="book-series"
                type="text"
                className="form-input"
                value={formData.series}
                onChange={e => handleChange('series', e.target.value)}
                onBlur={() => handleSave()}
                placeholder="e.g. Foundation, Book 1"
              />
            </div>

            <div className="form-group" data-tip-anchor="metadata-publisher">
              <label className="form-label" htmlFor="book-publisher">Publisher</label>
              <input
                id="book-publisher"
                type="text"
                className="form-input"
                value={formData.publisher}
                onChange={e => handleChange('publisher', e.target.value)}
                onBlur={() => handleSave()}
                placeholder="e.g. Penguin Classics"
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="book-subject">Subject / Genres</label>
            <input
              id="book-subject"
              type="text"
              className="form-input"
              value={formData.subject}
              onChange={e => handleChange('subject', e.target.value)}
              onBlur={() => handleSave()}
              placeholder="e.g. Science Fiction, Classic Literature"
            />
          </div>

          <div className="form-group" data-tip-anchor="metadata-description">
            <label className="form-label" htmlFor="book-desc">Description / Synopsis</label>
            <textarea
              id="book-desc"
              className="form-textarea"
              rows={4}
              value={formData.description}
              onChange={e => handleChange('description', e.target.value)}
              onBlur={() => handleSave()}
              placeholder="Brief summary or publisher blurb..."
            />
          </div>
        </div>

        <div className="drawer-footer">
          <div className="drawer-footer-status">
            {saving ? (
              <span className="text-xs text-muted">Saving changes…</span>
            ) : saveSuccess ? (
              <span className="text-xs text-success flex items-center gap-1">
                <Check size={14} /> Saved
              </span>
            ) : (
              <span className="text-xs text-muted">Auto-saves on change</span>
            )}
          </div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => { handleSave(); onClose(); }}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
