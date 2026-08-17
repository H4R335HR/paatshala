"""
Roulette wheel component for Streamlit.
Renders a spinning wheel via st.iframe() for visual presenter selection.
"""

import streamlit as st
import json
import math


# Vibrant color palettes
VOLUNTEER_COLORS = [
    '#667eea', '#764ba2', '#11998e', '#38ef7d', '#4facfe',
    '#00f2fe', '#43e97b', '#fa709a', '#fee140', '#a18cd1',
    '#fbc2eb', '#8fd3f4', '#84fab0', '#f6d365', '#fda085',
]

RANDOM_COLORS = [
    '#f7971e', '#ffd200', '#ff6b6b', '#ee5a24', '#f0932b',
    '#e056fd', '#686de0', '#30336b', '#eb4d4b', '#6ab04c',
    '#c7ecee', '#dff9fb', '#f9ca24', '#f0932b', '#eb4d4b',
]


def render_roulette(
    names: list[str],
    winner_index: int,
    mode: str = 'volunteer',
    wheel_id: str = 'roulette',
    height: int = 520,
):
    """
    Render a roulette wheel that spins and lands on the pre-selected winner.
    
    Args:
        names: List of participant names for wheel segments
        winner_index: Index into `names` of the pre-selected winner (0-based)
        mode: 'volunteer' (green/blue tones) or 'random' (orange/red tones)
        wheel_id: Unique DOM ID for the canvas element
        height: Height of the component in pixels
    """
    colors = VOLUNTEER_COLORS if mode == 'volunteer' else RANDOM_COLORS
    title = '🙋 Volunteer Roulette' if mode == 'volunteer' else '🎲 Random Draft'
    
    # Build segment colors (cycle through palette)
    segment_colors = [colors[i % len(colors)] for i in range(len(names))]
    
    names_json = json.dumps(names)
    colors_json = json.dumps(segment_colors)
    
    html = f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        
        .roulette-container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            font-family: 'Inter', sans-serif;
            padding: 16px 0;
            user-select: none;
        }}
        
        .roulette-title {{
            font-size: 1.3em;
            font-weight: 700;
            color: #fff;
            margin-bottom: 16px;
            text-align: center;
        }}
        
        .wheel-wrapper {{
            position: relative;
            display: inline-block;
        }}
        
        .wheel-pointer {{
            position: absolute;
            top: -8px;
            left: 50%;
            transform: translateX(-50%);
            width: 0;
            height: 0;
            border-left: 14px solid transparent;
            border-right: 14px solid transparent;
            border-top: 28px solid #fff;
            z-index: 10;
            filter: drop-shadow(0 2px 6px rgba(0,0,0,0.5));
        }}
        
        canvas {{
            border-radius: 50%;
            box-shadow: 0 0 30px rgba(102, 126, 234, 0.3), 0 0 60px rgba(102, 126, 234, 0.1);
        }}
        
        .winner-banner {{
            margin-top: 20px;
            padding: 16px 32px;
            border-radius: 12px;
            font-size: 1.4em;
            font-weight: 800;
            text-align: center;
            opacity: 0;
            transform: scale(0.8);
            transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
            background: linear-gradient(135deg, rgba(102,126,234,0.3), rgba(118,75,162,0.3));
            border: 2px solid rgba(255,255,255,0.2);
            color: #fff;
        }}
        
        .winner-banner.show {{
            opacity: 1;
            transform: scale(1);
        }}
        
        .confetti {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1000;
            overflow: hidden;
        }}
        
        .confetti-piece {{
            position: absolute;
            width: 10px;
            height: 10px;
            opacity: 0;
        }}
    </style>
    
    <div class="roulette-container">
        <div class="roulette-title">{title}</div>
        <div class="wheel-wrapper">
            <div class="wheel-pointer"></div>
            <canvas id="{wheel_id}" width="380" height="380"></canvas>
        </div>
        <div class="winner-banner" id="{wheel_id}_winner"></div>
    </div>
    <div class="confetti" id="{wheel_id}_confetti"></div>
    
    <script>
    (function() {{
        const names = {names_json};
        const colors = {colors_json};
        const winnerIndex = {winner_index};
        const canvas = document.getElementById('{wheel_id}');
        const ctx = canvas.getContext('2d');
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = 180;
        const numSegments = names.length;
        const segmentAngle = (2 * Math.PI) / numSegments;
        
        let currentAngle = 0;
        let spinning = false;
        let spinComplete = false;
        
        function drawWheel(rotation) {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // Outer ring glow
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius + 4, 0, 2 * Math.PI);
            ctx.strokeStyle = 'rgba(255,255,255,0.15)';
            ctx.lineWidth = 3;
            ctx.stroke();
            
            for (let i = 0; i < numSegments; i++) {{
                const startAngle = rotation + i * segmentAngle;
                const endAngle = startAngle + segmentAngle;
                
                // Segment fill
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.arc(centerX, centerY, radius, startAngle, endAngle);
                ctx.closePath();
                ctx.fillStyle = colors[i];
                ctx.fill();
                
                // Segment border
                ctx.strokeStyle = 'rgba(0,0,0,0.3)';
                ctx.lineWidth = 1.5;
                ctx.stroke();
                
                // Text
                ctx.save();
                ctx.translate(centerX, centerY);
                ctx.rotate(startAngle + segmentAngle / 2);
                ctx.textAlign = 'right';
                ctx.fillStyle = '#fff';
                ctx.font = 'bold ' + Math.min(14, Math.max(9, Math.floor(180 / numSegments))) + 'px Inter, sans-serif';
                ctx.shadowColor = 'rgba(0,0,0,0.5)';
                ctx.shadowBlur = 3;
                
                // Truncate long names
                let displayName = names[i];
                if (displayName.length > 18) {{
                    displayName = displayName.substring(0, 16) + '…';
                }}
                ctx.fillText(displayName, radius - 12, 5);
                ctx.restore();
            }}
            
            // Center circle
            ctx.beginPath();
            ctx.arc(centerX, centerY, 28, 0, 2 * Math.PI);
            ctx.fillStyle = '#1a1a2e';
            ctx.fill();
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // Center dot
            ctx.beginPath();
            ctx.arc(centerX, centerY, 6, 0, 2 * Math.PI);
            ctx.fillStyle = '#667eea';
            ctx.fill();
        }}
        
        function spinWheel() {{
            if (spinning || spinComplete) return;
            spinning = true;
            
            // Calculate target angle so the winner segment is at the top (under the pointer)
            // Pointer is at top (270 degrees = 3π/2)
            // We want the middle of the winner's segment to align with the pointer
            const pointerAngle = -Math.PI / 2; // top
            const targetSegmentCenter = winnerIndex * segmentAngle + segmentAngle / 2;
            // Absolute rotation that places targetSegmentCenter at pointerAngle
            let targetAngle = pointerAngle - targetSegmentCenter;
            while (targetAngle < 0) targetAngle += 2 * Math.PI;
            // Compute delta from current position to target (handles re-spins correctly)
            let normalizedCurrent = currentAngle % (2 * Math.PI);
            if (normalizedCurrent < 0) normalizedCurrent += 2 * Math.PI;
            let delta = targetAngle - normalizedCurrent;
            if (delta < 1e-9) delta += 2 * Math.PI;
            // Add extra full rotations for visual effect (5-8 full rotations)
            const extraSpins = 5 + Math.floor(Math.random() * 4);
            const extraRotations = extraSpins * 2 * Math.PI;
            const totalRotation = extraRotations + delta;
            
            const duration = 4000; // 4 seconds
            const startTime = performance.now();
            const startAngle = currentAngle;
            
            function easeOutCubic(t) {{
                return 1 - Math.pow(1 - t, 4);
            }}
            
            function animate(now) {{
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const eased = easeOutCubic(progress);
                
                currentAngle = startAngle + totalRotation * eased;
                drawWheel(currentAngle);
                
                if (progress < 1) {{
                    requestAnimationFrame(animate);
                }} else {{
                    spinning = false;
                    spinComplete = true;
                    showWinner();
                }}
            }}
            
            requestAnimationFrame(animate);
        }}
        
        function showWinner() {{
            const banner = document.getElementById('{wheel_id}_winner');
            banner.innerHTML = '🎉 ' + names[winnerIndex] + ' 🎉';
            banner.classList.add('show');
            launchConfetti();
        }}
        
        function launchConfetti() {{
            const container = document.getElementById('{wheel_id}_confetti');
            const confettiColors = ['#667eea', '#764ba2', '#38ef7d', '#ffd200', '#ff6b6b', '#4facfe', '#fa709a'];
            
            for (let i = 0; i < 60; i++) {{
                const piece = document.createElement('div');
                piece.className = 'confetti-piece';
                piece.style.left = Math.random() * 100 + '%';
                piece.style.backgroundColor = confettiColors[Math.floor(Math.random() * confettiColors.length)];
                piece.style.width = (Math.random() * 8 + 5) + 'px';
                piece.style.height = (Math.random() * 8 + 5) + 'px';
                piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '0';
                piece.style.transform = 'rotate(' + Math.random() * 360 + 'deg)';
                container.appendChild(piece);
                
                const duration = 1500 + Math.random() * 2000;
                const delay = Math.random() * 500;
                
                piece.animate([
                    {{ top: '-10px', opacity: 1 }},
                    {{ top: '100%', opacity: 0 }}
                ], {{
                    duration: duration,
                    delay: delay,
                    easing: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                    fill: 'forwards'
                }});
            }}
            
            // Cleanup after animation
            setTimeout(() => {{
                container.innerHTML = '';
            }}, 4000);
        }}
        
        // Initial draw
        drawWheel(currentAngle);
        
        // Auto-start spin after a brief pause
        setTimeout(spinWheel, 600);
    }})();
    </script>
    """
    
    st.iframe(html, height=height)
