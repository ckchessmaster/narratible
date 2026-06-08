import { useState } from 'react'
import './index.css'

function App() {
  const [currentStep, setCurrentStep] = useState(1);

  return (
    <div className="app-container">
      <header className="header">
        <h1>Echo-Scribe</h1>
        <div className="wizard-steps">
          Step {currentStep} of 4
        </div>
      </header>

      <main className="wizard-container glass-panel p-6">
        {currentStep === 1 && (
          <div className="step-content">
            <h2>Step 1: Upload PDF</h2>
            <p>Upload your PDF document to begin parsing.</p>
            <button className="glass-button mt-4" onClick={() => setCurrentStep(2)}>Next Step</button>
          </div>
        )}
        {currentStep === 2 && (
          <div className="step-content">
            <h2>Step 2: Edit Chapters</h2>
            <p>Review and edit the extracted text and chapters.</p>
            <div className="flex gap-4 mt-4">
              <button className="glass-button secondary" onClick={() => setCurrentStep(1)}>Back</button>
              <button className="glass-button" onClick={() => setCurrentStep(3)}>Next Step</button>
            </div>
          </div>
        )}
        {currentStep === 3 && (
          <div className="step-content">
            <h2>Step 3: Configure TTS</h2>
            <p>Select your voice and generation settings.</p>
            <div className="flex gap-4 mt-4">
              <button className="glass-button secondary" onClick={() => setCurrentStep(2)}>Back</button>
              <button className="glass-button" onClick={() => setCurrentStep(4)}>Next Step</button>
            </div>
          </div>
        )}
        {currentStep === 4 && (
          <div className="step-content">
            <h2>Step 4: Export</h2>
            <p>Generate your audiobook and EPUB files.</p>
            <div className="flex gap-4 mt-4">
              <button className="glass-button secondary" onClick={() => setCurrentStep(3)}>Back</button>
              <button className="glass-button" onClick={() => alert('Exporting!')}>Export</button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
