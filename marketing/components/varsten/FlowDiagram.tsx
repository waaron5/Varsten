export function FlowDiagram() {
  return (
    <figure className="relative border border-border bg-background p-6">
      <figcaption className="mono mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.28em] text-ink-soft">
        <span>Fig 01 — Request path</span>
        <span>t = 42ms</span>
      </figcaption>

      <svg
        viewBox="0 0 480 520"
        role="img"
        aria-label="Architectural diagram of a Varsten proxied LLM request"
        className="h-auto w-full"
      >
        <defs>
          <marker
            id="arr"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="#111111" />
          </marker>
          <marker
            id="arrBlue"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="#1447e6" />
          </marker>
        </defs>

        {/* grid ticks */}
        <g stroke="#e5e5e5" strokeWidth="0.5">
          {Array.from({ length: 13 }).map((_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 40} x2="480" y2={i * 40} />
          ))}
          {Array.from({ length: 13 }).map((_, i) => (
            <line key={`v${i}`} x1={i * 40} y1="0" x2={i * 40} y2="520" />
          ))}
        </g>

        {/* Client node */}
        <g>
          <rect
            x="40"
            y="40"
            width="180"
            height="72"
            fill="#ffffff"
            stroke="#111111"
            strokeWidth="1"
          />
          <text x="52" y="62" fontFamily="Inter" fontSize="12" fill="#111111" fontWeight="500">
            Client application
          </text>
          <text
            x="52"
            y="82"
            fontFamily="JetBrains Mono"
            fontSize="10"
            fill="#6b6b6b"
          >
            POST /v1/chat/completions
          </text>
          <text
            x="52"
            y="98"
            fontFamily="JetBrains Mono"
            fontSize="10"
            fill="#6b6b6b"
          >
            model: gpt-4o
          </text>
          <text
            x="52"
            y="34"
            fontFamily="JetBrains Mono"
            fontSize="9"
            fill="#6b6b6b"
          >
            A
          </text>
        </g>

        {/* arrow down to Varsten */}
        <line
          x1="130"
          y1="112"
          x2="130"
          y2="188"
          stroke="#111111"
          strokeWidth="1"
          markerEnd="url(#arr)"
        />
        <text
          x="138"
          y="152"
          fontFamily="JetBrains Mono"
          fontSize="10"
          fill="#6b6b6b"
        >
          prompt
        </text>

        {/* Varsten Proxy */}
        <g>
          <rect
            x="40"
            y="192"
            width="400"
            height="136"
            fill="#ffffff"
            stroke="#1447e6"
            strokeWidth="1"
          />
          <rect x="40" y="192" width="400" height="22" fill="#1447e6" />
          <text
            x="52"
            y="208"
            fontFamily="JetBrains Mono"
            fontSize="10"
            fill="#ffffff"
            letterSpacing="1"
          >
            VARSTEN · PROXY NODE
          </text>
          <text
            x="52"
            y="186"
            fontFamily="JetBrains Mono"
            fontSize="9"
            fill="#6b6b6b"
          >
            B
          </text>

          {/* internal stages */}
          {[
            ["route", 60],
            ["cache", 145],
            ["trim", 230],
            ["compress", 315],
          ].map(([label, x]) => (
            <g key={label as string}>
              <rect
                x={x as number}
                y="238"
                width="70"
                height="60"
                fill="#ffffff"
                stroke="#111111"
                strokeWidth="1"
              />
              <text
                x={(x as number) + 35}
                y="272"
                fontFamily="Inter"
                fontSize="11"
                fill="#111111"
                textAnchor="middle"
                fontWeight="500"
              >
                {label}
              </text>
              <circle
                cx={(x as number) + 35}
                cy="288"
                r="2"
                fill="#1447e6"
              />
            </g>
          ))}
        </g>

        {/* arrow down to provider */}
        <line
          x1="240"
          y1="328"
          x2="240"
          y2="404"
          stroke="#111111"
          strokeWidth="1"
          markerEnd="url(#arr)"
        />
        <text
          x="248"
          y="368"
          fontFamily="JetBrains Mono"
          fontSize="10"
          fill="#6b6b6b"
        >
          optimized · routed
        </text>

        {/* Provider */}
        <g>
          <rect
            x="150"
            y="408"
            width="180"
            height="72"
            fill="#ffffff"
            stroke="#111111"
            strokeWidth="1"
          />
          <text
            x="162"
            y="430"
            fontFamily="Inter"
            fontSize="12"
            fill="#111111"
            fontWeight="500"
          >
            LLM provider
          </text>
          <text
            x="162"
            y="450"
            fontFamily="JetBrains Mono"
            fontSize="10"
            fill="#6b6b6b"
          >
            openai · anthropic
          </text>
          <text
            x="162"
            y="466"
            fontFamily="JetBrains Mono"
            fontSize="10"
            fill="#6b6b6b"
          >
            gemini
          </text>
          <text
            x="162"
            y="402"
            fontFamily="JetBrains Mono"
            fontSize="9"
            fill="#6b6b6b"
          >
            C
          </text>
        </g>

        {/* return path (blueprint) */}
        <path
          d="M 330 444 L 420 444 L 420 76 L 220 76"
          fill="none"
          stroke="#1447e6"
          strokeWidth="1"
          strokeDasharray="3 3"
          markerEnd="url(#arrBlue)"
        />
        <g transform="rotate(-90 428 260)">
          <rect
            x="426"
            y="240"
            width="132"
            height="28"
            fill="#ffffff"
            stroke="#1447e6"
            strokeWidth="0.5"
          />
          <text
            x="432"
            y="258"
            fontFamily="JetBrains Mono"
            fontSize="9"
            fill="#1447e6"
            fontWeight="500"
          >
            response · lower cost
          </text>
        </g>
      </svg>

      <div className="mono mt-4 flex items-center justify-between border-t border-border pt-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
        <span>A → client</span>
        <span>B → proxy</span>
        <span>C → provider</span>
      </div>
    </figure>
  );
}
