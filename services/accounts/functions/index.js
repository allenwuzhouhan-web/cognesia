import {initializeApp} from 'firebase-admin/app';
import {getAuth} from 'firebase-admin/auth';
import {getFirestore} from 'firebase-admin/firestore';
import {onRequest} from 'firebase-functions/v2/https';
import {defineString, defineBoolean} from 'firebase-functions/params';
import {makeApp} from './app.js';

initializeApp();
const accountOrigin = defineString('ACCOUNT_ORIGIN');
const phoneEnabled = defineBoolean('PHONE_SIGNUP_ENABLED', {default: false});
let handler;
export const accounts = onRequest({region: 'asia-southeast1', maxInstances: 1,
  minInstances: 0, concurrency: 20, memory: '256MiB', timeoutSeconds: 15, cors: false}, (req, res) => {
  handler ??= makeApp({db: getFirestore(), auth: getAuth(),
    origin: accountOrigin.value(), phoneEnabled: phoneEnabled.value()});
  return handler(req, res);
});
