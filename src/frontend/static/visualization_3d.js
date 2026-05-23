// ============================================================
// FULL-SCREEN 3D AGENT VISUALIZATION - FLOATING BUTTON VERSION
// ============================================================

// Open full-screen overlay
window.openVizFullscreen = function() {
    const overlay = document.getElementById('viz-fullscreen');
    if (overlay) {
        overlay.style.display = 'flex';

        const delay = window.agentVizInitialized ? 100 : 600;

        if (!window.agentVizInitialized) {
            setTimeout(() => {
                initializeVisualization();
                window.agentVizInitialized = true;
            }, 200);
        }

        // Play any animation that was queued while the panel was closed
        if (window._pendingAnimation) {
            const pending = window._pendingAnimation;
            window._pendingAnimation = null;
            setTimeout(() => {
                if (window._runAnimation) window._runAnimation(pending);
            }, delay);
        }
    }
};

// Close full-screen overlay
window.closeVizFullscreen = function() {
    const overlay = document.getElementById('viz-fullscreen');
    if (overlay) {
        overlay.style.display = 'none';
    }
};

// Global trigger - runs animation if viz is open, otherwise stores it for when user opens
window.triggerAgentAnimation = function(responseData) {
    console.log("🎬 Animation queued:", responseData);
    window._pendingAnimation = responseData;

    const overlay = document.getElementById('viz-fullscreen');
    const isOpen = overlay && overlay.style.display !== 'none' && overlay.style.display !== '';

    if (isOpen && window._runAnimation) {
        setTimeout(() => {
            window._runAnimation(responseData);
            window._pendingAnimation = null;
        }, window.agentVizInitialized ? 100 : 600);
    }
    // If closed, animation will fire when user opens via openVizFullscreen
};

function initializeVisualization() {
    console.log("🎨 Initializing Full-Screen 3D Visualization...");

    const canvas = document.getElementById('viz-fullscreen-canvas');
    if (!canvas) {
        console.error("❌ Canvas not found!");
        return;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x87CEEB);

    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 10, 22);
    camera.lookAt(0, 2, 0);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xfff5e6, 0.9);
    sunLight.position.set(15, 25, 12);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.width = 2048;
    sunLight.shadow.mapSize.height = 2048;
    scene.add(sunLight);

    // Floor
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(60, 45),
        new THREE.MeshStandardMaterial({ color: 0xD5D5D5, roughness: 0.85 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    // Grid
    const grid = new THREE.GridHelper(60, 60, 0xcccccc, 0xe0e0e0);
    grid.position.y = 0.01;
    scene.add(grid);

    // Walls
    const wallMaterial = new THREE.MeshStandardMaterial({ color: 0xE8DAEF });

    const backWall = new THREE.Mesh(new THREE.PlaneGeometry(60, 20), wallMaterial);
    backWall.position.set(0, 10, -22);
    backWall.receiveShadow = true;
    scene.add(backWall);

    const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(45, 20), wallMaterial);
    leftWall.position.set(-30, 10, 0);
    leftWall.rotation.y = Math.PI / 2;
    scene.add(leftWall);

    // Windows
    for (let i = 0; i < 3; i++) {
        const win = new THREE.Mesh(
            new THREE.PlaneGeometry(4, 5),
            new THREE.MeshStandardMaterial({
                color: 0x87CEEB,
                emissive: 0x87CEEB,
                emissiveIntensity: 0.4
            })
        );
        win.position.set(-10 + i * 10, 7, -21.9);
        scene.add(win);
    }

    // Desk
    const deskTop = new THREE.Mesh(
        new THREE.BoxGeometry(8, 0.18, 4),
        new THREE.MeshStandardMaterial({ color: 0x8B4513 })
    );
    deskTop.position.set(-10, 1.6, -7);
    deskTop.castShadow = true;
    scene.add(deskTop);

    // Desk legs
    for (let i = 0; i < 4; i++) {
        const leg = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.1, 1.6, 8),
            new THREE.MeshStandardMaterial({ color: 0x654321 })
        );
        const xOff = i % 2 === 0 ? -3.5 : 3.5;
        const zOff = i < 2 ? -1.7 : 1.7;
        leg.position.set(-10 + xOff, 0.8, -7 + zOff);
        leg.castShadow = true;
        scene.add(leg);
    }

    // Computer monitor
    const monitorFrame = new THREE.Mesh(
        new THREE.BoxGeometry(2.4, 1.6, 0.15),
        new THREE.MeshStandardMaterial({ color: 0x1a1a1a })
    );
    monitorFrame.position.set(-3, 1.4, -2.5);
    monitorFrame.castShadow = true;
    scene.add(monitorFrame);

    const screenDisplay = new THREE.Mesh(
        new THREE.PlaneGeometry(2.2, 1.4),
        new THREE.MeshStandardMaterial({
            color: 0x0a0a0a,
            emissive: 0x00FF00,
            emissiveIntensity: 0.0
        })
    );
    screenDisplay.position.set(-3, 1.4, -2.42);
    scene.add(screenDisplay);

    // Server Racks (replacing file cabinets)
    function createServerRack(x, z) {
        const rack = new THREE.Group();

        // Main case
        const body = new THREE.Mesh(
            new THREE.BoxGeometry(1.3, 2.6, 0.85),
            new THREE.MeshStandardMaterial({ color: 0x7f8c8d, metalness: 0.4 })
        );
        body.position.y = 1.3;
        body.castShadow = true;
        rack.add(body);

        // 6 slots + LEDs
        const ledColors = [0x00ff88, 0x00ffff, 0xff4400, 0xffaa00, 0x0088ff, 0x00ff88];
        for (let i = 0; i < 6; i++) {
            const slot = new THREE.Mesh(
                new THREE.BoxGeometry(1.1, 0.32, 0.04),
                new THREE.MeshStandardMaterial({ color: 0x2c3e50 })
            );
            slot.position.set(0, 2.4 - i * 0.38, 0.445);
            rack.add(slot);

            const led = new THREE.Mesh(
                new THREE.SphereGeometry(0.04, 8, 8),
                new THREE.MeshStandardMaterial({
                    color: ledColors[i],
                    emissive: ledColors[i],
                    emissiveIntensity: 1.8
                })
            );
            led.position.set(0.42, 2.4 - i * 0.38, 0.47);
            rack.add(led);
        }

        rack.position.set(x, 0, z);
        rack.userData.body = body;
        return rack;
    }

    const serverRack1 = createServerRack(9, 5.5);
    const serverRack2 = createServerRack(10.9, 5.5);
    const serverRack3 = createServerRack(12.8, 5.5);
    scene.add(serverRack1);
    scene.add(serverRack2);
    scene.add(serverRack3);

    // Aliases for existing A2A path code that references fileCabinet1/2
    const fileCabinet1 = serverRack1;
    const fileCabinet2 = serverRack2;

    // MCP Tools
    function createTool(color, x, z) {
        const tool = new THREE.Mesh(
            new THREE.BoxGeometry(0.8, 0.8, 0.8),
            new THREE.MeshStandardMaterial({
                color,
                emissive: color,
                emissiveIntensity: 0.5,
                metalness: 0.6
            })
        );
        tool.position.set(x, 1.78, z);
        tool.castShadow = true;
        tool.userData = { initialY: 1.78 };
        return tool;
    }

    const alertsTool = createTool(0xFF4757, -11.5, -7);
    scene.add(alertsTool);

    const vehiclesTool = createTool(0x1E90FF, -10, -7);
    scene.add(vehiclesTool);

    const routesTool = createTool(0xFFA502, -8.5, -7);
    scene.add(routesTool);

    // MCP Tools label sprite
    (function() {
        const labelCanvas = document.createElement('canvas');
        labelCanvas.width = 340;
        labelCanvas.height = 72;
        const lctx = labelCanvas.getContext('2d');
        lctx.fillStyle = 'rgba(10,20,50,0.82)';
        lctx.fillRect(0, 0, 340, 72);
        lctx.strokeStyle = '#00aaff';
        lctx.lineWidth = 2;
        lctx.strokeRect(1, 1, 338, 70);
        lctx.font = 'bold 28px Arial';
        lctx.fillStyle = '#00ddff';
        lctx.textAlign = 'center';
        lctx.textBaseline = 'middle';
        lctx.fillText('MCP Tools', 170, 36);
        const tex = new THREE.CanvasTexture(labelCanvas);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
        sprite.position.set(-10, 3.2, -7);
        sprite.scale.set(3.4, 0.72, 1);
        scene.add(sprite);
    })();

    // Create robots with articulated limbs
    function createRobot(color, name) {
        const robot = new THREE.Group();
        const mat = (c) => new THREE.MeshStandardMaterial({ color: c, metalness: 0.4, roughness: 0.6 });
        const hexColor = color;

        // Torso
        const torso = new THREE.Mesh(new THREE.BoxGeometry(1.0, 1.15, 0.58), mat(hexColor));
        torso.position.y = 1.08;
        torso.castShadow = true;
        robot.add(torso);

        // Shoulder pads
        [-0.6, 0.6].forEach(sx => {
            const pad = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.18, 0.54), mat(hexColor));
            pad.position.set(sx, 1.55, 0);
            robot.add(pad);
        });

        // Chest panel (dark inset)
        const chestPanel = new THREE.Mesh(
            new THREE.BoxGeometry(0.6, 0.5, 0.04),
            new THREE.MeshStandardMaterial({ color: 0x1a1a2e })
        );
        chestPanel.position.set(0, 1.1, 0.31);
        robot.add(chestPanel);

        // Power core (glowing sphere)
        const core = new THREE.Mesh(
            new THREE.SphereGeometry(0.1, 12, 12),
            new THREE.MeshStandardMaterial({
                color: 0x00eeff,
                emissive: 0x00eeff,
                emissiveIntensity: 2.5
            })
        );
        core.position.set(0, 1.15, 0.33);
        robot.add(core);

        // Glass dome over core
        const dome = new THREE.Mesh(
            new THREE.SphereGeometry(0.13, 12, 12),
            new THREE.MeshStandardMaterial({
                color: 0xaaeeff,
                transparent: true,
                opacity: 0.25,
                metalness: 0.1
            })
        );
        dome.position.copy(core.position);
        robot.add(dome);

        // Neck
        const neck = new THREE.Mesh(
            new THREE.CylinderGeometry(0.11, 0.14, 0.2, 10),
            mat(hexColor)
        );
        neck.position.y = 1.7;
        robot.add(neck);

        // Head
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.6, 0.62), mat(hexColor));
        head.position.y = 2.1;
        head.castShadow = true;
        robot.add(head);

        // Crown cylinder on top of head
        const crown = new THREE.Mesh(
            new THREE.CylinderGeometry(0.2, 0.32, 0.14, 10),
            mat(hexColor)
        );
        crown.position.y = 2.47;
        robot.add(crown);

        // Visor (dark box at front of head)
        const visor = new THREE.Mesh(
            new THREE.BoxGeometry(0.65, 0.22, 0.06),
            new THREE.MeshStandardMaterial({
                color: 0x0a0a1a,
                emissive: hexColor,
                emissiveIntensity: 0.3
            })
        );
        visor.position.set(0, 2.1, 0.34);
        robot.add(visor);

        // Eyes (two small spheres behind visor)
        const eyeMat = new THREE.MeshStandardMaterial({
            color: 0x00ffff,
            emissive: 0x00ffff,
            emissiveIntensity: 1.5
        });
        const leftEye = new THREE.Mesh(new THREE.SphereGeometry(0.055, 8, 8), eyeMat.clone());
        leftEye.position.set(-0.15, 2.1, 0.32);
        robot.add(leftEye);
        const rightEye = new THREE.Mesh(new THREE.SphereGeometry(0.055, 8, 8), eyeMat.clone());
        rightEye.position.set(0.15, 2.1, 0.32);
        robot.add(rightEye);

        // Antenna stick
        const antennaMat = new THREE.MeshStandardMaterial({ color: 0x34495E });
        const antennaStick = new THREE.Mesh(
            new THREE.CylinderGeometry(0.03, 0.03, 0.45, 8),
            antennaMat
        );
        antennaStick.position.set(0.15, 2.62, 0);
        robot.add(antennaStick);

        // Antenna tip
        const antennaTip = new THREE.Mesh(
            new THREE.SphereGeometry(0.07, 10, 10),
            new THREE.MeshStandardMaterial({
                color: 0xff3333,
                emissive: 0xff3333,
                emissiveIntensity: 1.2
            })
        );
        antennaTip.position.set(0.15, 2.87, 0);
        robot.add(antennaTip);

        // LEFT ARM group (pivot at shoulder)
        const leftArmGroup = new THREE.Group();
        leftArmGroup.position.set(-0.62, 1.42, 0);
        leftArmGroup.rotation.z = -Math.PI / 6;

        const leftUpperArm = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.09, 0.52, 10),
            mat(hexColor)
        );
        leftUpperArm.position.y = -0.26;
        leftArmGroup.add(leftUpperArm);

        const leftElbow = new THREE.Mesh(
            new THREE.SphereGeometry(0.1, 8, 8),
            mat(hexColor)
        );
        leftElbow.position.y = -0.54;
        leftArmGroup.add(leftElbow);

        const leftForearm = new THREE.Mesh(
            new THREE.CylinderGeometry(0.085, 0.075, 0.44, 10),
            mat(hexColor)
        );
        leftForearm.position.y = -0.78;
        leftArmGroup.add(leftForearm);

        const leftHand = new THREE.Mesh(
            new THREE.SphereGeometry(0.09, 8, 8),
            mat(hexColor)
        );
        leftHand.position.y = -1.02;
        leftArmGroup.add(leftHand);

        robot.add(leftArmGroup);

        // RIGHT ARM group (pivot at shoulder)
        const rightArmGroup = new THREE.Group();
        rightArmGroup.position.set(0.62, 1.42, 0);
        rightArmGroup.rotation.z = Math.PI / 6;

        const rightUpperArm = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.09, 0.52, 10),
            mat(hexColor)
        );
        rightUpperArm.position.y = -0.26;
        rightArmGroup.add(rightUpperArm);

        const rightElbow = new THREE.Mesh(
            new THREE.SphereGeometry(0.1, 8, 8),
            mat(hexColor)
        );
        rightElbow.position.y = -0.54;
        rightArmGroup.add(rightElbow);

        const rightForearm = new THREE.Mesh(
            new THREE.CylinderGeometry(0.085, 0.075, 0.44, 10),
            mat(hexColor)
        );
        rightForearm.position.y = -0.78;
        rightArmGroup.add(rightForearm);

        const rightHand = new THREE.Mesh(
            new THREE.SphereGeometry(0.09, 8, 8),
            mat(hexColor)
        );
        rightHand.position.y = -1.02;
        rightArmGroup.add(rightHand);

        robot.add(rightArmGroup);

        // LEFT LEG group (pivot at hip)
        const leftLegGroup = new THREE.Group();
        leftLegGroup.position.set(-0.28, 0.48, 0);

        const leftThigh = new THREE.Mesh(
            new THREE.CylinderGeometry(0.13, 0.11, 0.44, 10),
            mat(hexColor)
        );
        leftThigh.position.y = -0.22;
        leftLegGroup.add(leftThigh);

        const leftKnee = new THREE.Mesh(
            new THREE.SphereGeometry(0.115, 8, 8),
            mat(hexColor)
        );
        leftKnee.position.y = -0.48;
        leftLegGroup.add(leftKnee);

        const leftShin = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.09, 0.42, 10),
            mat(hexColor)
        );
        leftShin.position.y = -0.72;
        leftLegGroup.add(leftShin);

        const leftFoot = new THREE.Mesh(
            new THREE.BoxGeometry(0.22, 0.1, 0.34),
            mat(hexColor)
        );
        leftFoot.position.set(0, -0.97, 0.06);
        leftLegGroup.add(leftFoot);

        robot.add(leftLegGroup);

        // RIGHT LEG group (pivot at hip)
        const rightLegGroup = new THREE.Group();
        rightLegGroup.position.set(0.28, 0.48, 0);

        const rightThigh = new THREE.Mesh(
            new THREE.CylinderGeometry(0.13, 0.11, 0.44, 10),
            mat(hexColor)
        );
        rightThigh.position.y = -0.22;
        rightLegGroup.add(rightThigh);

        const rightKnee = new THREE.Mesh(
            new THREE.SphereGeometry(0.115, 8, 8),
            mat(hexColor)
        );
        rightKnee.position.y = -0.48;
        rightLegGroup.add(rightKnee);

        const rightShin = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.09, 0.42, 10),
            mat(hexColor)
        );
        rightShin.position.y = -0.72;
        rightLegGroup.add(rightShin);

        const rightFoot = new THREE.Mesh(
            new THREE.BoxGeometry(0.22, 0.1, 0.34),
            mat(hexColor)
        );
        rightFoot.position.set(0, -0.97, 0.06);
        rightLegGroup.add(rightFoot);

        robot.add(rightLegGroup);

        // Canvas label sprite
        const canvas2d = document.createElement('canvas');
        const ctx = canvas2d.getContext('2d');
        canvas2d.width = 256;
        canvas2d.height = 72;
        const texture = new THREE.CanvasTexture(canvas2d);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture }));
        sprite.position.set(0, 3.6, 0);
        sprite.scale.set(2.8, 0.72, 1);
        robot.add(sprite);

        robot.userData = {
            name,
            color: hexColor,
            antennaTip,
            core,
            eyes: [leftEye, rightEye],
            arms: [leftArmGroup, rightArmGroup],
            legs: [leftLegGroup, rightLegGroup],
            label: sprite,
            labelCanvas: canvas2d,
            labelContext: ctx,
            walkTime: 0,
            isWalking: false
        };

        // Draw initial label
        return robot;
    }

    // Create 5 robots
    const userRobot = createRobot(0x3498DB, 'User');
    userRobot.position.set(-16, 0, 0);
    userRobot.userData.home = { x: -16, y: 0, z: 0 };
    scene.add(userRobot);

    // Add HUGE VISIBLE phone in front of User robot's face
    const phoneBody = new THREE.Mesh(
        new THREE.BoxGeometry(0.35, 0.65, 0.08),
        new THREE.MeshStandardMaterial({
            color: 0x1a1a1a,
            metalness: 0.8,
            roughness: 0.2
        })
    );
    phoneBody.position.set(0.65, 0.8, 0.6);
    phoneBody.castShadow = true;
    userRobot.add(phoneBody);

    // Phone screen (GLOWING BRIGHT BLUE)
    const phoneScreen = new THREE.Mesh(
        new THREE.PlaneGeometry(0.3, 0.55),
        new THREE.MeshStandardMaterial({
            color: 0x001a33,
            emissive: 0x00BFFF,
            emissiveIntensity: 1.8
        })
    );
    phoneScreen.position.set(0.65, 0.8, 0.65);
    phoneScreen.rotation.x = -0.25;
    userRobot.add(phoneScreen);

    // Store phone reference
    userRobot.userData.phone = phoneScreen;

    const exchangeRobot = createRobot(0x9B59B6, 'Exchange');
    exchangeRobot.position.set(-5, 0, -2);
    exchangeRobot.userData.home = { x: -5, y: 0, z: -2 };
    scene.add(exchangeRobot);

    const alertsRobot = createRobot(0xE74C3C, 'Alerts');
    alertsRobot.position.set(9, 0, 5);
    alertsRobot.userData.home = { x: 9, y: 0, z: 5 };
    scene.add(alertsRobot);

    const plannerRobot = createRobot(0x27AE60, 'Planner');
    plannerRobot.position.set(9, 0, -4);
    plannerRobot.userData.home = { x: 9, y: 0, z: -4 };
    scene.add(plannerRobot);

    const stopfinderRobot = createRobot(0xF39C12, 'StopFinder');
    stopfinderRobot.position.set(9, 0, 0.5);
    stopfinderRobot.userData.home = { x: 9, y: 0, z: 0.5 };
    scene.add(stopfinderRobot);

    // Agent station rings on floor
    const stationRingDefs = [
        { robot: userRobot,        color: 0x3498DB },
        { robot: exchangeRobot,    color: 0x9B59B6 },
        { robot: alertsRobot,      color: 0xE74C3C },
        { robot: plannerRobot,     color: 0x27AE60 },
        { robot: stopfinderRobot,  color: 0xF39C12 }
    ];
    stationRingDefs.forEach(({ robot, color }) => {
        const ring = new THREE.Mesh(
            new THREE.TorusGeometry(0.9, 0.04, 8, 64),
            new THREE.MeshStandardMaterial({
                color,
                emissive: color,
                emissiveIntensity: 0.6,
                transparent: true,
                opacity: 0.7
            })
        );
        ring.rotation.x = -Math.PI / 2;
        ring.position.set(robot.position.x, 0.02, robot.position.z);
        scene.add(ring);
    });

    // Update label
    function updateLabel(robot, status) {
        const ctx = robot.userData.labelContext;
        const canvas = robot.userData.labelCanvas;

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'rgba(0,0,0,0.85)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const statusColors = {
            'Idle':          '#607d8b',
            'Walking':       '#29b6f6',
            'Thinking':      '#ffa726',
            'Working':       '#ef5350',
            'Communicating': '#ab47bc',
            'Complete':      '#66bb6a'
        };

        const statusColor = statusColors[status] || '#667eea';
        ctx.strokeStyle = statusColor;
        ctx.lineWidth = 3;
        ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);

        ctx.font = 'bold 20px Arial';
        ctx.fillStyle = 'white';
        ctx.textAlign = 'center';
        ctx.fillText(robot.userData.name, canvas.width / 2, 28);

        ctx.font = '15px Arial';
        ctx.fillStyle = statusColor;
        ctx.fillText(status, canvas.width / 2, 52);

        robot.userData.label.material.map.needsUpdate = true;
    }

    // Initialize labels
    [userRobot, exchangeRobot, alertsRobot, plannerRobot, stopfinderRobot].forEach(r => updateLabel(r, 'Idle'));

    // Walking animation using group rotation
    function animateWalking(robot) {
        if (robot.userData.isWalking) {
            robot.userData.walkTime += 0.13;
            const t = robot.userData.walkTime;
            const legs = robot.userData.legs;
            const arms = robot.userData.arms;

            legs[0].rotation.x = Math.sin(t) * 0.55;
            legs[1].rotation.x = Math.sin(t + Math.PI) * 0.55;
            arms[0].rotation.x = Math.sin(t + Math.PI) * 0.38;
            arms[1].rotation.x = Math.sin(t) * 0.38;
        } else {
            const legs = robot.userData.legs;
            const arms = robot.userData.arms;
            legs[0].rotation.x = 0;
            legs[1].rotation.x = 0;
            arms[0].rotation.x = 0;
            arms[1].rotation.x = 0;
            arms[0].rotation.z = -Math.PI / 6;
            arms[1].rotation.z = Math.PI / 6;
        }
    }

    // Idle animations (core pulse, antenna blink)
    function animateIdle(robot, time) {
        const { core, antennaTip } = robot.userData;
        if (core) {
            core.material.emissiveIntensity = 2.0 + Math.sin(time * 2.2) * 0.8;
        }
        if (antennaTip) {
            antennaTip.material.emissiveIntensity = 0.9 + Math.sin(time * 3.5) * 0.4;
        }
    }

    // Move robot
    function moveRobotTo(robot, target, duration, callback) {
        const start = { x: robot.position.x, z: robot.position.z };
        const startTime = Date.now();
        robot.userData.isWalking = true;
        updateLabel(robot, 'Walking');

        const dx = target.x - start.x;
        const dz = target.z - start.z;
        robot.rotation.y = Math.atan2(dx, dz);

        function animMove() {
            const elapsed = Date.now() - startTime;
            const progress = Math.min(elapsed / (duration * 1000), 1);

            robot.position.x = start.x + dx * progress;
            robot.position.z = start.z + dz * progress;

            if (progress < 1) {
                requestAnimationFrame(animMove);
            } else {
                robot.userData.isWalking = false;
                updateLabel(robot, 'Idle');
                if (callback) callback();
            }
        }
        animMove();
    }

    // Safe status update
    function updateStatus(text) {
        const statusEl = document.getElementById('viz-fullscreen-status');
        if (statusEl) {
            statusEl.textContent = text;
        }
    }

    // ============================================================
    // COMMUNICATION EFFECTS
    // ============================================================

    let _activeBeam = null;

    function spawnBeam(fromPos, toPos, color) {
        if (_activeBeam) {
            scene.remove(_activeBeam);
            _activeBeam.geometry.dispose();
            _activeBeam.material.dispose();
            _activeBeam = null;
        }
        const mid = {
            x: (fromPos.x + toPos.x) / 2,
            y: Math.max(fromPos.y, toPos.y) + 4.5,
            z: (fromPos.z + toPos.z) / 2
        };
        const curve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(fromPos.x, fromPos.y + 2.8, fromPos.z),
            new THREE.Vector3(mid.x, mid.y, mid.z),
            new THREE.Vector3(toPos.x, toPos.y + 2.8, toPos.z)
        );
        const pts = curve.getPoints(40);
        const geo = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 40, 0.04, 6, false);
        const mat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 2.0, transparent: true, opacity: 0.75
        });
        _activeBeam = new THREE.Mesh(geo, mat);
        scene.add(_activeBeam);
    }

    function removeBeam() {
        if (_activeBeam) {
            scene.remove(_activeBeam);
            _activeBeam.geometry.dispose();
            _activeBeam.material.dispose();
            _activeBeam = null;
        }
    }

    function spawnPackets(fromPos, toPos, color, durationMs) {
        const curve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(fromPos.x, fromPos.y + 2.8, fromPos.z),
            new THREE.Vector3(
                (fromPos.x + toPos.x) / 2,
                Math.max(fromPos.y, toPos.y) + 4.5,
                (fromPos.z + toPos.z) / 2
            ),
            new THREE.Vector3(toPos.x, toPos.y + 2.8, toPos.z)
        );
        const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 3.0 });
        const packets = [];
        for (let i = 0; i < 5; i++) {
            const m = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 8), mat.clone());
            scene.add(m);
            packets.push({ mesh: m, offset: i / 5 });
        }
        const start = Date.now();
        const speed = 1.0 / (durationMs * 0.001);
        function tick() {
            const elapsed = (Date.now() - start) * 0.001;
            if (elapsed > durationMs * 0.001 + 0.5) {
                packets.forEach(p => {
                    scene.remove(p.mesh);
                    p.mesh.geometry.dispose();
                    p.mesh.material.dispose();
                });
                return;
            }
            packets.forEach(p => {
                const t = ((elapsed * speed + p.offset) % 1.0);
                p.mesh.position.copy(curve.getPoint(t));
                p.mesh.material.emissiveIntensity = 2.5 + Math.sin(elapsed * 10 + p.offset * 6) * 0.8;
            });
            requestAnimationFrame(tick);
        }
        tick();
    }

    function spawnPulseRing(pos, color) {
        const mat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 2.0,
            transparent: true, opacity: 0.9, side: THREE.DoubleSide
        });
        const mesh = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.05, 8, 32), mat);
        mesh.rotation.x = Math.PI / 2;
        mesh.position.set(pos.x, 0.05, pos.z);
        scene.add(mesh);
        const start = Date.now();
        function tick() {
            const t = (Date.now() - start) * 0.001;
            const s = 1 + t * 3.5;
            mesh.scale.set(s, s, s);
            mat.opacity = Math.max(0, 0.9 - t * 1.2);
            if (t < 0.75) requestAnimationFrame(tick);
            else {
                scene.remove(mesh);
                mesh.geometry.dispose();
                mat.dispose();
            }
        }
        tick();
    }

    // Animation runner
    window._runAnimation = function(responseData) {
        const path = responseData.path;
        const agents = responseData.agents_called || [];
        const latency = responseData.latency_ms || 0;

        updateStatus(`Processing: ${path.toUpperCase()} path | ${latency}ms`);

        if (path === 'mcp' || path === 'shortcut') {
            runMCPPath(latency);
        } else {
            runA2APath(agents, latency);
        }
    };

    // MCP Path
    function runMCPPath(latency) {
        updateLabel(userRobot, 'Working');
        updateLabel(exchangeRobot, 'Working');
        updateStatus('MCP Path: Exchange walking to desk...');

        moveRobotTo(exchangeRobot, { x: -10, y: 0, z: -5 }, 1.8, () => {
            exchangeRobot.userData.arms[1].rotation.z = -Math.PI / 2;
            exchangeRobot.userData.antennaTip.material.emissiveIntensity = 1.5;
            alertsTool.material.emissiveIntensity = 1.5;
            spawnPulseRing({ x: -10, z: -7 }, 0x0088ff);

            updateStatus('Using MCP tool: mbta_get_alerts');

            setTimeout(() => {
                alertsTool.material.emissiveIntensity = 0.5;
                exchangeRobot.userData.arms[1].rotation.z = -Math.PI / 6;

                updateStatus('Returning to computer with data...');

                moveRobotTo(exchangeRobot, { x: -4, y: 0, z: -2.5 }, 1.8, () => {
                    exchangeRobot.rotation.y = -Math.PI / 2;
                    exchangeRobot.userData.arms[1].rotation.z = -Math.PI / 3;

                    updateStatus('Feeding data to computer screen...');

                    setTimeout(() => {
                        // Computer screen glows
                        screenDisplay.material.emissiveIntensity = 1.2;

                        // PHONE BLINKS (synchronized with screen glow)
                        console.log("📱 Phone blinking now!");
                        let blinkCount = 0;
                        const phoneBlinkInterval = setInterval(() => {
                            if (userRobot.userData.phone) {
                                const intensity = blinkCount % 2 === 0 ? 5.0 : 0.0;
                                userRobot.userData.phone.material.emissiveIntensity = intensity;
                                console.log(`📱 Blink ${blinkCount}: intensity ${intensity}`);
                            }
                            blinkCount++;

                            if (blinkCount >= 14) {
                                clearInterval(phoneBlinkInterval);
                                if (userRobot.userData.phone) {
                                    userRobot.userData.phone.material.emissiveIntensity = 1.8;
                                }
                                console.log("📱 Blinking complete");
                            }
                        }, 100);

                        setTimeout(() => {
                            screenDisplay.material.emissiveIntensity = 0.3;

                            moveRobotTo(exchangeRobot, exchangeRobot.userData.home, 1.5, () => {
                                exchangeRobot.rotation.y = 0;
                                exchangeRobot.userData.arms[1].rotation.z = Math.PI / 6;
                                updateLabel(exchangeRobot, 'Complete');
                                updateLabel(userRobot, 'Complete');

                                if (userRobot.userData.phone) {
                                    userRobot.userData.phone.material.emissiveIntensity = 1.5;
                                }

                                updateStatus(`✓ MCP Path Complete (${latency}ms)`);

                                setTimeout(() => {
                                    updateLabel(exchangeRobot, 'Idle');
                                    updateLabel(userRobot, 'Idle');

                                    if (userRobot.userData.phone) {
                                        userRobot.userData.phone.material.emissiveIntensity = 0.8;
                                    }
                                }, 2000);
                            });
                        }, 1800);
                    }, 600);
                });
            }, 1800);
        });
    }

    // A2A Path
    function runA2APath(agentsCalled, latency) {
        updateLabel(userRobot, 'Working');
        updateLabel(exchangeRobot, 'Working');
        updateStatus('A2A Path: Multi-agent coordination...');

        // Map agent IDs to robot objects — includes all name variants
        const robotMap = {
            'mbta-alerts':      alertsRobot,
            'mbta-planner':     plannerRobot,
            'mbta-stopfinder':  stopfinderRobot,
            'mbta-stops':       stopfinderRobot
        };

        // Build ordered visit list: skip errors, deduplicate robots
        const seen = new Set();
        const agentsToVisit = agentsCalled
            .filter(name => !name.includes('_error') && robotMap[name])
            .map(name => ({ robot: robotMap[name], name }))
            .filter(({ robot }) => {
                if (seen.has(robot)) return false;
                seen.add(robot);
                return true;
            });

        if (agentsToVisit.length === 0) {
            agentsToVisit.push(
                { robot: alertsRobot,  name: 'mbta-alerts' },
                { robot: plannerRobot, name: 'mbta-planner' }
            );
        }

        let idx = 0;

        // After all agents are visited, walk to computer and finish
        function finishAtComputer() {
            exchangeRobot.rotation.y = 0;
            updateStatus('Returning to computer with synthesized response...');

            moveRobotTo(exchangeRobot, { x: -4, y: 0, z: -2.5 }, 2.0, () => {
                exchangeRobot.rotation.y = -Math.PI / 2;
                exchangeRobot.userData.arms[1].rotation.z = -Math.PI / 3;
                updateLabel(exchangeRobot, 'Working');

                setTimeout(() => {
                    screenDisplay.material.emissiveIntensity = 1.2;
                    updateStatus('Synthesizing and feeding data to screen...');

                    // Phone blinks synchronized with screen glow
                    if (userRobot.userData.phone) {
                        let blinkCount = 0;
                        const blinkInterval = setInterval(() => {
                            userRobot.userData.phone.material.emissiveIntensity = blinkCount % 2 === 0 ? 5.0 : 0.0;
                            blinkCount++;
                            if (blinkCount >= 14) {
                                clearInterval(blinkInterval);
                                userRobot.userData.phone.material.emissiveIntensity = 1.8;
                            }
                        }, 100);
                    }

                    setTimeout(() => {
                        screenDisplay.material.emissiveIntensity = 0.3;

                        moveRobotTo(exchangeRobot, exchangeRobot.userData.home, 1.8, () => {
                            exchangeRobot.rotation.y = 0;
                            exchangeRobot.userData.arms[1].rotation.z = Math.PI / 6;
                            updateLabel(exchangeRobot, 'Complete');
                            updateLabel(userRobot, 'Complete');

                            if (userRobot.userData.phone) {
                                userRobot.userData.phone.material.emissiveIntensity = 1.5;
                            }

                            updateStatus(`✓ A2A Complete — ${agentsToVisit.length} agent(s) (${latency}ms)`);

                            setTimeout(() => {
                                updateLabel(exchangeRobot, 'Idle');
                                updateLabel(userRobot, 'Idle');
                                if (userRobot.userData.phone) {
                                    userRobot.userData.phone.material.emissiveIntensity = 0.8;
                                }
                            }, 3000);
                        });
                    }, 2000);
                }, 800);
            });
        }

        function visitNext() {
            if (idx >= agentsToVisit.length) {
                finishAtComputer();
                return;
            }

            const { robot: target, name: agentName } = agentsToVisit[idx];
            const agentHome = target.userData.home;

            const exchangePos  = { x: agentHome.x - 3.8, y: 0, z: agentHome.z };
            const agentMeetPos = { x: agentHome.x - 2.0, y: 0, z: agentHome.z };

            updateStatus(`Exchange → ${target.userData.name} agent...`);

            moveRobotTo(exchangeRobot, exchangePos, 2.0, () => {
                // Target steps out to meet exchange
                moveRobotTo(target, agentMeetPos, 0.9, () => {
                    // Face each other
                    exchangeRobot.rotation.y =  Math.PI / 2;
                    target.rotation.y         = -Math.PI / 2;

                    updateLabel(exchangeRobot, 'Communicating');
                    updateLabel(target, 'Thinking');

                    exchangeRobot.userData.antennaTip.material.emissiveIntensity = 1.8;
                    target.userData.antennaTip.material.emissiveIntensity = 1.8;

                    // Spawn communication effects
                    spawnBeam(exchangeRobot.position, target.position, 0x00eeff);
                    spawnPackets(exchangeRobot.position, target.position, 0x00eeff, 2600);
                    spawnPulseRing(target.position, 0x00ff88);

                    // Special effects per agent type
                    if (target.userData.name === 'Alerts') {
                        updateStatus('Alerts: Live MBTA data + 41,970 historical incidents...');
                        setTimeout(() => {
                            fileCabinet1.userData.body.material.emissive = new THREE.Color(0xFF4757);
                            fileCabinet1.userData.body.material.emissiveIntensity = 0.9;
                            fileCabinet2.userData.body.material.emissive = new THREE.Color(0xFF4757);
                            fileCabinet2.userData.body.material.emissiveIntensity = 0.7;
                            setTimeout(() => {
                                fileCabinet1.userData.body.material.emissiveIntensity = 0;
                                fileCabinet2.userData.body.material.emissiveIntensity = 0;
                            }, 2200);
                        }, 300);
                    } else if (target.userData.name === 'Planner') {
                        updateStatus('Planner: Computing optimal routes with alerts context...');
                    } else {
                        updateStatus(`${target.userData.name}: Resolving station locations...`);
                    }

                    // End communication after 2600ms
                    setTimeout(() => {
                        removeBeam();
                        exchangeRobot.userData.antennaTip.material.emissiveIntensity = 0.7;
                        target.userData.antennaTip.material.emissiveIntensity = 0.7;
                        updateLabel(target, 'Complete');

                        // Target returns home; exchange resets rotation then moves to next
                        moveRobotTo(target, target.userData.home, 1.0, () => {
                            target.rotation.y = 0;
                            updateLabel(target, 'Idle');
                            exchangeRobot.rotation.y = 0;
                            idx++;
                            setTimeout(visitNext, 400);
                        });
                    }, 2600);
                });
            });
        }

        visitNext();
    }

    // Animation loop
    function animate() {
        requestAnimationFrame(animate);

        const time = Date.now() * 0.001;

        [userRobot, exchangeRobot, alertsRobot, plannerRobot, stopfinderRobot].forEach(robot => {
            animateWalking(robot);
            animateIdle(robot, time);
        });

        [alertsTool, vehiclesTool, routesTool].forEach((tool, i) => {
            tool.position.y = tool.userData.initialY + Math.sin(time + i * 1.2) * 0.12;
            tool.rotation.y += 0.01;
        });

        if (controls) controls.update();

        renderer.render(scene, camera);
    }

    // OrbitControls
    let controls = null;
    if (typeof THREE.OrbitControls !== 'undefined') {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.06;
        controls.minDistance = 8;
        controls.maxDistance = 45;
        controls.maxPolarAngle = Math.PI / 2.1;
        controls.target.set(0, 2, 0);
        controls.update();
    }

    animate();

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    console.log("✅ Full-Screen 3D Visualization Ready!");
}
