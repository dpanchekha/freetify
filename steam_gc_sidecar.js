#!/usr/bin/env node
'use strict';

// This process deliberately talks only over stdin/stdout with Freetify. It has
// no HTTP server and never writes Steam secrets to its own logs.
const readline = require('readline');
const SteamUser = require('steam-user');
const NodeCS2 = require('node-cs2');
const QRCode = require('qrcode');
const {LoginSession, EAuthTokenPlatformType} = require('steam-session');

let client = null;
let cs2 = null;
let loginSession = null;
let state = 'disconnected';
let steamid = null;
let connectionTimer = null;
// Steam defaults client logons to ID 0. A unique nonzero ID prevents this
// helper from replacing the desktop Steam client on the same network.
const logonID = Math.floor(Math.random() * 0xffffffff) || 1;

function send(type, payload = {}) {
  process.stdout.write(`${JSON.stringify({type, state, steamid, ...payload}, jsonReplacer)}\n`);
}

function jsonReplacer(key, value) {
  if (typeof value === 'bigint') return value.toString();
  if (value && typeof value === 'object' && typeof value.low === 'number' && typeof value.high === 'number' && typeof value.toString === 'function') return value.toString();
  return value;
}

function setState(next, detail = '') {
  state = next;
  send('status', {detail});
}

function publicError(error, context = 'Steam connection failed') {
  const message = error && error.message ? error.message : String(error || 'Unknown error');
  if (/LogonSessionReplaced|LoggedInElsewhere|AlreadyLoggedInElsewhere/i.test(message)) {
    closeClient();
    setState('error', 'Steam replaced Freetify’s CS2 connection. Click Connect CS2 and approve a fresh QR sign-in. If it repeats, close any other Freetify window and fully exit CS2 before reconnecting.');
    return;
  }
  setState('error', `${context}: ${message}`);
}

function closeClient() {
  if (connectionTimer) clearTimeout(connectionTimer);
  connectionTimer = null;
  if (client) {
    try { client.logOff(); } catch (_) {}
  }
  client = null;
  cs2 = null;
}

function startClient(refreshToken) {
  closeClient();
  setState('connecting', 'Connecting to Steam and CS2…');
  client = new SteamUser({autoRelogin: true, renewRefreshTokens: true});
  cs2 = new NodeCS2(client);
  const connectingClient = client;
  connectionTimer = setTimeout(() => {
    if (client === connectingClient && (state === 'connecting' || state === 'connecting_gc')) {
      closeClient();
      setState('error', 'CS2 did not finish connecting in time. Click Connect CS2 to try a fresh QR sign-in.');
    }
  }, 12000);

  client.on('error', error => publicError(error, 'Steam client error'));
  client.on('loggedOn', () => {
    steamid = client.steamID.getSteamID64();
    setState('connecting_gc', 'Steam connected; requesting CS2 match history…');
    client.gamesPlayed([730]);
    setTimeout(() => { if (cs2) cs2.helloGC(); }, 1000);
  });
  client.on('refreshToken', token => send('refresh_token', {refresh_token: token}));
  cs2.on('error', error => publicError(error, 'CS2 Game Coordinator error'));
  cs2.on('connectedToGC', () => { if (connectionTimer) clearTimeout(connectionTimer); connectionTimer = null; setState('ready', 'CS2 match history is ready.'); });
  cs2.on('disconnectedFromGC', () => { if (client && cs2 && state !== 'error') setState('connecting_gc', 'CS2 connection was interrupted; retrying…'); });
  cs2.on('matchList', matches => send('matches', {matches}));

  try {
    client.logOn({refreshToken, machineName: 'Freetify', logonID});
  } catch (error) {
    publicError(error);
  }
}

async function startQr() {
  // A new QR login is an explicit recovery action. Tear down any stalled
  // refresh-token session first so it cannot keep the UI in "connecting".
  closeClient();
  if (loginSession) {
    try { loginSession.cancelLoginAttempt(); } catch (_) {}
  }
  loginSession = new LoginSession(EAuthTokenPlatformType.SteamClient, {machineId: true});
  loginSession.loginTimeout = 120000;
  loginSession.on('error', error => publicError(error, 'Steam QR sign-in failed'));
  loginSession.on('timeout', () => setState('error', 'Steam QR sign-in timed out. Generate a new code and try again.'));
  loginSession.on('remoteInteraction', () => setState('waiting_for_approval', 'Steam recognized the QR code. Approve the sign-in in the Steam mobile app.'));
  loginSession.on('authenticated', () => {
    const token = loginSession.refreshToken;
    steamid = loginSession.steamID.getSteamID64();
    send('refresh_token', {refresh_token: token});
    startClient(token);
  });
  try {
    const result = await loginSession.startWithQR();
    const qr = await QRCode.toDataURL(result.qrChallengeUrl, {margin: 1, width: 260});
    setState('waiting_for_qr', 'Scan this code in the Steam mobile app, then approve the sign-in.');
    send('qr', {image: qr});
  } catch (error) {
    publicError(error, 'Could not generate a Steam QR code');
  }
}

function requestRecentGames() {
  if (!cs2 || state !== 'ready' || !steamid) {
    send('error', {detail: 'CS2 is not ready yet. Finish Steam QR sign-in and wait for the CS2 connection.'});
    return;
  }
  try {
    cs2.requestRecentGames(steamid);
    setState('loading_matches', 'Requesting recent matches from CS2…');
  } catch (error) {
    publicError(error, 'Could not request recent CS2 matches');
  }
}

function requestGame(shareCode) {
  if (!cs2 || state !== 'ready') {
    send('error', {detail: 'CS2 is not ready yet. Finish Steam QR sign-in and wait for the CS2 connection.'});
    return;
  }
  try {
    cs2.requestGame(shareCode);
    setState('loading_matches', 'Requesting match details from CS2…');
  } catch (error) {
    publicError(error, 'Could not request this CS2 match');
  }
}

readline.createInterface({input: process.stdin, crlfDelay: Infinity}).on('line', line => {
  try {
    const command = JSON.parse(line);
    if (command.type === 'start_qr') startQr();
    else if (command.type === 'connect' && command.refresh_token) startClient(command.refresh_token);
    else if (command.type === 'recent_matches') requestRecentGames();
    else if (command.type === 'match' && command.share_code) requestGame(command.share_code);
    else if (command.type === 'status') send('status');
    else if (command.type === 'shutdown') { closeClient(); process.exit(0); }
  } catch (error) {
    publicError(error, 'Invalid Freetify Steam bridge command');
  }
});

send('status', {detail: 'Steam bridge started.'});
