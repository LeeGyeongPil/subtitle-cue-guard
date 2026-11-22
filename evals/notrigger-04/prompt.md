---
name: notrigger-04
max_turns: 8
---

Why does my React component re-render on every keystroke? Here is the code: function Form() { const [v, setV] = useState(''); return <input value={v} onChange={e => setV(e.target.value)} /> }
