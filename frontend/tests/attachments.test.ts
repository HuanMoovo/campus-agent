import { describe, expect, it } from 'vitest'

import {
  attachmentAccept, attachmentKind, attachmentSuffix, attachmentTextProblem, fileExtension,
} from '../src/attachments'

describe('attachmentKind', () => {
  it('classifies local text, backend-extract and rejected files', () => {
    expect(attachmentKind('notes.txt')).toBe('text')
    expect(attachmentKind('README.MD')).toBe('text')
    expect(attachmentKind('data.csv')).toBe('text')
    expect(attachmentKind('main.py')).toBe('text')
    expect(attachmentKind('通知.pdf')).toBe('extract')
    expect(attachmentKind('招生简章.docx')).toBe('extract')
    expect(attachmentKind('photo.png')).toBe('reject')
    expect(attachmentKind('archive.zip')).toBe('reject')
    expect(attachmentKind('noextension')).toBe('reject')
  })
})

describe('fileExtension / attachmentAccept / attachmentSuffix', () => {
  it('parses extensions and builds the accept list', () => {
    expect(fileExtension('a.tar.gz')).toBe('gz')
    expect(fileExtension('plain')).toBe('')
    const accept = attachmentAccept()
    expect(accept).toContain('.txt')
    expect(accept).toContain('.pdf')
    expect(accept.startsWith('.')).toBe(true)
  })

  it('builds the display suffix', () => {
    expect(attachmentSuffix(['a.txt', 'b.md'])).toBe('[附件] a.txt、b.md')
  })
})

describe('attachmentTextProblem', () => {
  it('flags empty and oversized texts', () => {
    expect(attachmentTextProblem('   ')).toBe('chat.attachEmpty')
    expect(attachmentTextProblem('x'.repeat(200_001))).toBe('chat.attachTooLarge')
    expect(attachmentTextProblem('正常内容')).toBeNull()
  })
})
