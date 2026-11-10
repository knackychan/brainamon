import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import ts from '../web/node_modules/typescript/lib/typescript.js'
import { parse } from '../web/node_modules/svelte/src/compiler/index.js'

const immediateMethods = new Set(['from', 'map', 'flatMap', 'forEach', 'filter', 'reduce', 'reduceRight', 'find', 'findIndex', 'some', 'every', 'sort'])

export function eagerTranslations(text, filename) {
  if (filename.endsWith('.svelte')) {
    const script = parse(text, { modern: true }).module?.content
    if (!script) return []
    text = text.slice(script.start, script.end)
  }
  const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const names = new Set(), functions = new Map(), found = [], active = new Set()
  for (const statement of source.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier)) {
      const from = statement.moduleSpecifier.text
      if ((from.includes('i18n') || (filename.includes('/i18n/') && from === './index.ts')) && statement.importClause?.namedBindings && ts.isNamedImports(statement.importClause.namedBindings)) {
        for (const specifier of statement.importClause.namedBindings.elements)
          if ((specifier.propertyName ?? specifier.name).text === 't') names.add(specifier.name.text)
      }
    }
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
      functions.set(statement.name.text, statement.body)
      if (statement.name.text === 't' && filename.endsWith('/i18n/index.ts')) names.add('t')
    }
    if (ts.isVariableStatement(statement)) for (const decl of statement.declarationList.declarations)
      if (ts.isIdentifier(decl.name) && decl.initializer && (ts.isArrowFunction(decl.initializer) || ts.isFunctionExpression(decl.initializer)))
        functions.set(decl.name.text, decl.initializer.body)
  }
  function body(fn) {
    if (active.has(fn)) return
    active.add(fn); visit(fn); active.delete(fn)
  }
  function visit(node) {
    if (ts.isFunctionLike(node)) return
    if (ts.isCallExpression(node)) {
      let callee = node.expression
      while (ts.isParenthesizedExpression(callee)) callee = callee.expression
      if (ts.isIdentifier(callee)) {
        if (names.has(callee.text)) found.push(callee.text)
        else if (functions.has(callee.text)) body(functions.get(callee.text))
      } else if (ts.isArrowFunction(callee) || ts.isFunctionExpression(callee)) body(callee.body)
      if (ts.isPropertyAccessExpression(callee) && immediateMethods.has(callee.name.text))
        for (const arg of node.arguments) {
          if (ts.isArrowFunction(arg) || ts.isFunctionExpression(arg)) body(arg.body)
          else if (ts.isIdentifier(arg) && functions.has(arg.text)) body(functions.get(arg.text))
        }
    }
    ts.forEachChild(node, visit)
  }
  for (const statement of source.statements) visit(statement)
  return found
}

function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const name = path.join(directory, entry.name)
    return entry.isDirectory() ? files(name) : /\.(?:ts|svelte)$/.test(name) ? [name] : []
  })
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve('tests/check_phone_i18n_ast.mjs')) {
  const prefix = "import { t } from './lib/i18n/index.ts'; "
  assert.equal(eagerTranslations(prefix + 'const lazy = () => t("x");', 'test.ts').length, 0)
  assert.equal(eagerTranslations(prefix + 'const x = t("x");', 'test.ts').length, 1)
  assert.equal(eagerTranslations(prefix + 'const f = () => t("x"); const x = f();', 'test.ts').length, 1)
  assert.equal(eagerTranslations(prefix + 'const x = (() => t("x"))();', 'test.ts').length, 1)
  assert.equal(eagerTranslations(prefix + 'const x = [1].map(() => t("x"));', 'test.ts').length, 1)
  assert.equal(eagerTranslations(prefix + 'const f = () => t("x"); const x = [1].map(f);', 'test.ts').length, 1)
  assert.equal(eagerTranslations(prefix + 'const x = Array.from([1], () => t("x"));', 'test.ts').length, 1)
  assert.equal(eagerTranslations(`<script>${prefix}const x = t('x')</script>`, 'test.svelte').length, 0)
  assert.equal(eagerTranslations(`<script module>${prefix}const x = t('x')</script>`, 'test.svelte').length, 1)
  const roots = ['web/src/mobile', 'web/src/lib', 'web/src/components', 'web/src/windows']
  const errors = roots.flatMap(root => files(root)).flatMap(file => {
    const normalized = file.replaceAll('\\', '/')
    // The phone entry deliberately renders startup copy after its synchronous setup call.
    if (normalized === 'web/src/mobile/main.ts') {
      const text = fs.readFileSync(file, 'utf8')
      const setup = text.indexOf('const selected = setup(')
      assert.ok(setup >= 0 && setup < text.search(/\bt\s*\(/), 'phone startup must set up i18n before rendering')
      return []
    }
    return eagerTranslations(fs.readFileSync(file, 'utf8'), normalized).map(() => normalized)
  })
  if (errors.length) throw new Error(`Import-time translations: ${errors.join(', ')}`)
  console.log('Import-time translation scan passed')
}
