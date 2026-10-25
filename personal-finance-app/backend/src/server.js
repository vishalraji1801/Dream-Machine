import { startServer } from './app.js';

const PORT = Number(process.env.PORT ?? 4000);

startServer({ port: PORT, host: '0.0.0.0' }).then(() => {
  console.log(`LenDen API listening on http://localhost:${PORT}`);
});
