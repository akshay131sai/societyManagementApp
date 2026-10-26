/**
 * The live notification socket.
 *
 * Design notes worth keeping:
 *
 * - **The socket is an optimisation, not a source of truth.** Every event it
 *   delivers has a row behind it, so a dropped connection costs nothing but
 *   freshness. That is why there is no replay, no sequence number and no
 *   acknowledgement — a reconnect simply refetches the feed.
 *
 * - **Reconnection backs off.** A backend restart must not turn 300 open tabs
 *   into 300 reconnects per second. The delay doubles to 30s and resets on a
 *   successful open.
 *
 * - **A hidden tab does not reconnect.** Someone with the app open in a
 *   background tab for a week should not hold a socket for it; the connection
 *   is dropped when the page is hidden and re-established on return, which
 *   also refetches the feed and closes the gap.
 */

import * as React from "react";

import { getAccessToken } from "@/services/auth";
import type { RealtimeMessage } from "@/types";

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

function socketUrl(token: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
  if (/^https?:/i.test(base)) {
    return `${base.replace(/^http/i, "ws")}/ws?token=${encodeURIComponent(token)}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${base}/ws?token=${encodeURIComponent(token)}`;
}

export interface RealtimeOptions {
  enabled: boolean;
  /** Called for every `notification` event. Kept in a ref, so it may change. */
  onNotification: (message: RealtimeMessage) => void;
  /** Called on every (re)connect, to close the gap the disconnection left. */
  onReconnect?: () => void;
}

export function useRealtime({ enabled, onNotification, onReconnect }: RealtimeOptions): {
  connected: boolean;
} {
  const [connected, setConnected] = React.useState(false);

  // Handlers live in refs so a re-render does not tear the socket down.
  const notifyRef = React.useRef(onNotification);
  const reconnectRef = React.useRef(onReconnect);
  notifyRef.current = onNotification;
  reconnectRef.current = onReconnect;

  React.useEffect(() => {
    if (!enabled) return;

    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let delay = BASE_DELAY_MS;
    let closed = false;

    async function open() {
      if (closed || document.hidden) return;

      const token = await getAccessToken().catch(() => null);
      if (!token || closed) return;

      socket = new WebSocket(socketUrl(token));

      socket.onopen = () => {
        delay = BASE_DELAY_MS;
        setConnected(true);
        reconnectRef.current?.();
      };

      socket.onmessage = (event) => {
        let message: RealtimeMessage;
        try {
          message = JSON.parse(event.data as string) as RealtimeMessage;
        } catch {
          return;
        }
        // `ping` is the server's keepalive and `connected` the handshake ack;
        // neither is anything a screen should react to.
        if (message.type === "notification") notifyRef.current(message);
      };

      socket.onclose = () => {
        setConnected(false);
        socket = null;
        if (closed) return;
        retry = window.setTimeout(open, delay);
        delay = Math.min(delay * 2, MAX_DELAY_MS);
      };

      socket.onerror = () => socket?.close();
    }

    function onVisibility() {
      if (document.hidden) {
        socket?.close();
      } else if (!socket) {
        window.clearTimeout(retry);
        delay = BASE_DELAY_MS;
        void open();
      }
    }

    void open();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      closed = true;
      window.clearTimeout(retry);
      document.removeEventListener("visibilitychange", onVisibility);
      socket?.close();
    };
  }, [enabled]);

  return { connected };
}
