import {initializeApp, getApps, cert} from 'firebase-admin/app';
import {getAuth} from 'firebase-admin/auth';
import {getFirestore} from 'firebase-admin/firestore';
import {makeApp} from '../../functions/app.js';
import {makeNetlifyHandler,countryPolicy} from '../adapter.mjs';

let handler;
export default async (request, context) => {
  try {
    if (!handler) {
      const credentials = JSON.parse(process.env.COGNESIA_FIREBASE_SERVICE_ACCOUNT || '{}');
      if (credentials.project_id !== 'cognesia-accounts') throw new Error('Account project is not configured.');
      const origin = process.env.ACCOUNT_ORIGIN;
      const blockedCountries = countryPolicy(process.env.BLOCKED_COUNTRIES);
      const firebase = getApps().find(app=>app.name==='cognesia-accounts') ||
        initializeApp({credential:cert(credentials),projectId:credentials.project_id},'cognesia-accounts');
      handler = makeNetlifyHandler(makeApp({db:getFirestore(firebase),
        auth:getAuth(firebase),origin,phoneEnabled:false,googleEnabled:true}),
        {origin,blockedCountries});
    }
    return await handler(request,context);
  } catch {
    // Credentials, contacts and request bodies must never enter logs.
    return Response.json({error:{message:'Account service is temporarily unavailable.'}},
      {status:503,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  }
};
export const config = {path:['/api/*','/v1/access'],preferStatic:false};
