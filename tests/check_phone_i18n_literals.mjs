import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import ts from '../web/node_modules/typescript/lib/typescript.js'
import { parse } from '../web/node_modules/svelte/src/compiler/index.js'

const attributes = new Set(['aria-label', 'title', 'placeholder', 'alt', 'label', 'summary', 'desc', 'infoTitle'])
const sinks = new Set(['toast', 'alert', 'confirm', 'Error'])
const visible = text => /[\p{L}]/u.test(text.trim())

export function candidates(text, filename, sharedProperties = new Set(), collectProperties = new Set()) {
  const found = [], seen = new Set(), displayed = new Set()
  const add = (value, at, kind) => {
    if (!visible(value)) return
    const line = text.slice(0, at).split('\n').length
    const key = `${line}:${kind}:${value}`
    if (!seen.has(key)) { seen.add(key); found.push({ line, kind, value: value.trim() }) }
  }
  function expression(node) {
    if (!node || typeof node !== 'object') return
    if (node.type === 'CallExpression' && node.callee?.type === 'Identifier' && node.callee.name === 't') return
    if (node.type === 'Identifier') displayed.add(node.name)
    if (node.type === 'MemberExpression' && !node.computed && node.property?.type === 'Identifier') collectProperties.add(node.property.name)
    if (node.type === 'Literal' && typeof node.value === 'string') add(node.value, node.start, 'expression')
    if (node.type === 'TemplateElement' && node.value?.cooked) add(node.value.cooked, node.start, 'expression')
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'parent'].includes(key)) continue
      if (Array.isArray(value)) value.forEach(expression)
      else if (value && typeof value === 'object') expression(value)
    }
  }
  function markup(node, parent = '') {
    if (!node || typeof node !== 'object') return
    if (node.type === 'Text' && parent !== 'Attribute') add(node.data, node.start, 'text')
    if (node.type === 'Attribute') {
      if (!attributes.has(node.name)) return
      for (const value of Array.isArray(node.value) ? node.value : [node.value]) {
        if (value?.type === 'Text') add(value.data, value.start, `attribute:${node.name}`)
        else expression(value?.expression)
      }
      return
    }
    if (node.type === 'ExpressionTag') { expression(node.expression); return }
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'parent', 'expression'].includes(key)) continue
      if (Array.isArray(value)) value.forEach(child => markup(child, node.type))
      else if (value && typeof value === 'object') markup(value, node.type)
    }
  }
  function script(code, offset = 0) {
    const source = ts.createSourceFile(filename, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    function rootName(node) {
      while (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) node = node.expression
      return ts.isIdentifier(node) ? node.text : ''
    }
    function assignedText(node) {
      if (!node) return
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 't') return
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node))
        add(node.text, offset + node.getStart(source), 'display-assignment')
      ts.forEachChild(node, assignedText)
    }
    const visit = node => {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && displayed.has(node.name.text)) assignedText(node.initializer)
      if (ts.isPropertyAssignment(node) && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) && sharedProperties.has(node.name.text)) assignedText(node.initializer)
      if (ts.isBinaryExpression(node) && ts.isAssignmentOperator(node.operatorToken.kind) &&
          (displayed.has(rootName(node.left)) || (ts.isPropertyAccessExpression(node.left) && sharedProperties.has(node.left.name.text)))) assignedText(node.right)
      if (ts.isFunctionDeclaration(node) && node.name && displayed.has(node.name.text)) {
        const returns = child => { if (ts.isReturnStatement(child)) assignedText(child.expression); else ts.forEachChild(child, returns) }
        if (node.body) returns(node.body)
      }
      if ((ts.isCallExpression(node) || ts.isNewExpression(node)) && ts.isIdentifier(node.expression) && sinks.has(node.expression.text)) {
        const first = node.arguments?.[0]
        if (first && (ts.isStringLiteral(first) || ts.isNoSubstitutionTemplateLiteral(first))) add(first.text, offset + first.getStart(source), `call:${node.expression.text}`)
        else if (first && ts.isTemplateExpression(first)) add(first.getText(source), offset + first.getStart(source), `call:${node.expression.text}`)
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  if (filename.endsWith('.svelte')) {
    const ast = parse(text, { modern: true })
    markup(ast.fragment)
    for (const part of [ast.module?.content, ast.instance?.content]) if (part) script(text.slice(part.start, part.end), part.start)
  } else script(text)
  return found
}

function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const name = path.join(directory, entry.name)
    return entry.isDirectory() ? files(name) : /\.(?:ts|svelte)$/.test(name) ? [name] : []
  })
}

export function unclassified(report, allowed) {
  for (const entry of allowed) {
    assert.ok(entry.file && Number.isInteger(entry.line) && entry.kind && entry.value && entry.reason)
    assert.ok(report.some(item => item.file === entry.file && item.line === entry.line && item.kind === entry.kind && item.value === entry.value), `Stale exemption: ${entry.file}:${entry.line}`)
  }
  return report.filter(item => !allowed.some(entry => item.file === entry.file && item.line === entry.line && item.kind === entry.kind && item.value === entry.value))
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve('tests/check_phone_i18n_literals.mjs')) {
  const fixture = candidates('<script>toast("Saved")</script><button aria-label="Back">Hello</button>', 'fixture.svelte')
  assert.deepEqual(new Set(fixture.map(item => item.kind)), new Set(['call:toast', 'attribute:aria-label', 'text']))
  assert.equal(candidates('<p>{t("common.retry")}</p>', 'fixture.svelte').length, 0)
  const assigned = candidates('<script>let msg=""; let mode="internal"; function label(){return "Open"} function save(){msg="Saved"}</script><p>{msg} {label()}</p>', 'fixture.svelte')
  assert.deepEqual(new Set(assigned.filter(item => item.kind === 'display-assignment').map(item => item.value)), new Set(['Open', 'Saved']))
  assert.ok(candidates('<script>let status={text:""}; function run(){status.text="Waiting"}</script><p>{status.text}</p>', 'fixture.svelte').some(item => item.value === 'Waiting'))
  const shared = new Set()
  candidates('<p>{phone.note}</p>', 'fixture.svelte', new Set(), shared)
  assert.ok(candidates('phone.note = "Saved"', 'fixture.ts', shared).some(item => item.value === 'Saved'))
  assert.ok(candidates('const state = { note: "Waiting" }', 'fixture.ts', shared).some(item => item.value === 'Waiting'))
  const plain = candidates('<img alt="Description"><button title="Help">Continue</button><p>{t("common.retry")}</p>', 'fixture.svelte')
  assert.deepEqual(new Set(plain.map(item => item.kind)), new Set(['attribute:alt', 'attribute:title', 'text']))
  const raw = plain.map(item => ({ file: 'fixture.svelte', ...item }))
  const exemption = { ...raw[0], reason: 'Exact synthetic fixture, positive/negative scanner self-check.' }
  assert.equal(unclassified(raw, []).length, raw.length)
  assert.equal(unclassified(raw, [exemption]).length, raw.length - 1)
  assert.throws(() => unclassified(raw, [{ ...exemption, value: 'changed text' }]), /Stale exemption/)
  assert.throws(() => unclassified(raw, [{ ...exemption, line: 999 }]), /Stale exemption/)
  const sharedFiles = ['web/src/components/ForgotPassphrase.svelte', 'web/src/components/LegalDocuments.svelte',
    'web/src/components/WiskitSprite.svelte', 'web/src/windows/AnalyzeOptionsForm.svelte',
    'web/src/components/ui/TaskSteps.svelte', 'web/src/components/ui/Progress.svelte', 'web/src/components/ui/DeletionEstimate.svelte',
    'web/src/lib/onboarding.ts', 'web/src/lib/ask-examples.ts', 'web/src/lib/backup.ts', 'web/src/lib/processing.ts']
  const sources = [...files('web/src/mobile'), ...sharedFiles].map(file => ({ file, text: fs.readFileSync(file, 'utf8') }))
  const properties = new Set()
  for (const source of sources) if (source.file.endsWith('.svelte')) candidates(source.text, source.file, new Set(), properties)
  const report = sources.flatMap(source => candidates(source.text, source.file, properties).map(item => ({ file: source.file.replaceAll('\\', '/'), ...item })))
  const allowed = JSON.parse(fs.readFileSync('tests/phone_i18n_allowlist.json', 'utf8'))
  const remaining = unclassified(report, allowed)
  if (!process.argv.includes('--report') && remaining.length) {
    console.error(JSON.stringify(remaining, null, 2)); process.exitCode = 1
  } else if (process.argv.includes('--report')) console.log(JSON.stringify(remaining, null, 2))
  else console.log(`Untranslated literal candidates: ${remaining.length}`)
}
