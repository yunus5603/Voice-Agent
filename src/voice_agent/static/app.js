const $ = selector => document.querySelector(selector);
const setupSection = $("#setup");
const room = $("#room");
const form = $("#setup-form");
const button = $("#connect");
const status = $("#status");
const events = $("#events");

let interview = null;
let socket;
let stream;
let audioContext;
let processor;
let source;
let nextPlaybackTime = 0;
let timerHandle = null;
let endsAt = null;
let finished = false;
const playbackNodes = new Set();

function addEvent(text, className = "") {
  const row = document.createElement("div");
  row.className = `event ${className}`;
  row.textContent = text;
  events.prepend(row);
}

function formatMs(value) {
  return value === null || value === undefined ? "–" : `${value} ms`;
}

function showMetrics({ turn, session }) {
  $("#m-last").textContent = formatMs(turn.response_ms);
  $("#m-p50").textContent = formatMs(session.response_p50_ms);
  $("#m-p95").textContent = formatMs(session.response_p95_ms);
  $("#m-turns").textContent = `${session.turns} · ${session.interruptions}`;
}

function showProgress(number, total) {
  $("#progress-bar").style.width = `${Math.round(((number - 1) / total) * 100)}%`;
  $("#progress-label").textContent = `Question ${number} of ${total}`;
  if (!endsAt) startTimer();
}

function renderTimer() {
  const left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
  const timer = $("#timer");
  timer.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  timer.classList.toggle("low", left <= 60);
}

function startTimer() {
  endsAt = Date.now() + interview.minutes * 60 * 1000;
  renderTimer();
  timerHandle = setInterval(renderTimer, 1000);
}

function finishInterview(questionsAsked) {
  finished = true;
  clearInterval(timerHandle);
  $("#progress-bar").style.width = "100%";
  $("#progress-label").textContent = `Interview complete · ${questionsAsked} questions`;
  addEvent("Interview complete. Your feedback report is coming in the next release.", "done");
  setTimeout(disconnect, 4000);
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const planButton = $("#plan");
  const setupStatus = $("#setup-status");
  const data = Object.fromEntries(new FormData(form));
  data.minutes = Number(data.minutes);
  planButton.disabled = true;
  setupStatus.textContent = "Reading the job description and planning your questions…";
  try {
    const response = await fetch("/api/interviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      setupStatus.textContent = response.status === 422
        ? "Please paste a longer job description (at least 40 characters)."
        : "Couldn't plan the interview. Please try again.";
      return;
    }
    interview = await response.json();
    $("#role-title").textContent = interview.role_title;
    $("#summary").textContent = `${interview.question_count} questions · about ${interview.minutes} minutes. ${interview.summary}`;
    $("#timer").textContent = `${interview.minutes}:00`;
    setupSection.hidden = true;
    room.hidden = false;
  } catch (error) {
    setupStatus.textContent = "Couldn't reach the server. Please try again.";
  } finally {
    planButton.disabled = false;
  }
});

function base64FromBytes(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function bytesFromBase64(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

function downsampleToPcm16(input, inputRate, outputRate = 16000) {
  const ratio = inputRate / outputRate;
  const length = Math.round(input.length / ratio);
  const output = new Int16Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.round(i * ratio);
    const end = Math.min(Math.round((i + 1) * ratio), input.length);
    let total = 0;
    for (let j = start; j < end; j++) total += input[j];
    const sample = Math.max(-1, Math.min(1, total / Math.max(1, end - start)));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return new Uint8Array(output.buffer);
}

function sampleRateFromMimeType(mimeType, fallback = 24000) {
  const match = /(?:^|;)\s*rate=(\d+)/i.exec(mimeType || "");
  return match ? Number(match[1]) : fallback;
}

function playPcm(base64, mimeType) {
  const sampleRate = sampleRateFromMimeType(mimeType);
  const bytes = bytesFromBase64(base64);
  const samples = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
  const buffer = audioContext.createBuffer(1, samples.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
  const node = audioContext.createBufferSource();
  node.buffer = buffer;
  node.connect(audioContext.destination);
  playbackNodes.add(node);
  node.addEventListener("ended", () => playbackNodes.delete(node));
  nextPlaybackTime = Math.max(nextPlaybackTime, audioContext.currentTime);
  node.start(nextPlaybackTime);
  nextPlaybackTime += buffer.duration;
}

async function connect() {
  audioContext = new AudioContext();
  await audioContext.resume();
  stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws?interview_id=${encodeURIComponent(interview.interview_id)}`);
  socket.addEventListener("open", () => {
    status.textContent = "Connected. The interviewer will greet you.";
    button.textContent = "End interview";
    button.classList.add("connected");
    source = audioContext.createMediaStreamSource(stream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = event => {
      if (socket?.readyState !== WebSocket.OPEN) return;
      const pcm = downsampleToPcm16(event.inputBuffer.getChannelData(0), audioContext.sampleRate);
      socket.send(JSON.stringify({ type: "audio", mime_type: "audio/pcm;rate=16000", data: base64FromBytes(pcm) }));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
  });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.type === "audio") playPcm(message.data, message.mime_type);
    if (message.type === "transcript") addEvent(`${message.speaker === "you" ? "You" : "Interviewer"}: ${message.text}`, message.speaker);
    if (message.type === "progress") showProgress(message.number, message.total);
    if (message.type === "interview_ended") finishInterview(message.questions_asked);
    if (message.type === "interrupted") {
      playbackNodes.forEach(node => { try { node.stop(); } catch (_) {} });
      playbackNodes.clear();
      nextPlaybackTime = audioContext.currentTime;
    }
    if (message.type === "metrics") showMetrics(message);
    if (message.type === "error") addEvent(message.message);
  });
  socket.addEventListener("close", event => {
    if (!finished && event.code === 1008) status.textContent = "This interview link has already been used. Plan a new one.";
    if (!finished && event.code === 1013) status.textContent = "The server is busy. Please try again in a minute.";
    disconnect();
  });
}

function disconnect() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "audio_stream_end" }));
    socket.close();
  }
  processor?.disconnect(); source?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  audioContext?.close();
  playbackNodes.clear();
  socket = stream = audioContext = processor = source = null;
  nextPlaybackTime = 0;
  clearInterval(timerHandle);
  button.textContent = "Plan another interview";
  button.classList.remove("connected");
}

button.addEventListener("click", async () => {
  if (button.textContent === "Plan another interview") { location.reload(); return; }
  try { socket ? disconnect() : await connect(); }
  catch (error) { status.textContent = error.message; disconnect(); }
});
