import { ready } from './lib/local-auth'
void ready().then(() => import('./main'))
