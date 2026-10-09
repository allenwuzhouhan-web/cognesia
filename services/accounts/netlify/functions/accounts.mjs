// Keep the external transport visible to Netlify's dependency tracer.
import '@google-cloud/firestore';
import runtime from '../accounts-runtime.cjs';

export default runtime.default;
export const config = {path:['/api/*','/v1/access'],preferStatic:false};
