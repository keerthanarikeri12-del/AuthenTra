import test from 'node:test';
import assert from 'node:assert/strict';
import {fileError, selectionError, referenceError, inspectFile} from '../src/uploadValidation.js';
const limits = {max_files: 5, max_file_bytes: 10 * 1024 * 1024, max_batch_bytes: 50 * 1024 * 1024};
const file = (name, type, size = 100) => ({name,type,size});
test('accepted formats, MIME mismatch, emptiness, extension and size', () => {
  for (const [ext,type] of [['pdf','application/pdf'],['png','image/png'],['jpg','image/jpeg'],['jpeg','image/jpeg']]) assert.equal(fileError(file('certificate.'+ext,type),limits),'');
  assert.ok(fileError(file('x.pdf','text/html'),limits));
  assert.ok(fileError(file('x.zip','application/zip'),limits));
  assert.ok(fileError(file('x.jpg','image/jpeg',0),limits));
  assert.ok(fileError(file('x.pdf','application/pdf',limits.max_file_bytes+1),limits));
});
test('five-file boundary and centrally supplied batch limits', () => {
  const item = {file:file('x.pdf','application/pdf')};
  assert.equal(selectionError(Array(5).fill(item),limits),'');
  assert.ok(selectionError(Array(6).fill(item),limits));
  assert.ok(selectionError([item,item],{...limits,max_batch_bytes:150}));
});
test('certificate reference validation', () => {
  assert.equal(referenceError(' at-001 '),'');
  for(const value of ['', '../unsafe', 'x'.repeat(65), '=formula']) assert.ok(referenceError(value));
});
test('unreadable files fail before any browser preview', async () => {
  await assert.rejects(inspectFile(new File(['bad'], 'broken.pdf', {type:'application/pdf'}),limits),/readable PDF/);
  await assert.rejects(inspectFile(new File(['bad'], 'broken.png', {type:'image/png'}),limits),/contents do not match/);
});
