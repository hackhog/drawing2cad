// 3D view for tab 4 (ADR 0010): GLB from the server (meshed from STEP), neutral grey with edges as in CAD.
// Loaded with React.lazy, so that three.js does not slow down the overview.
import { Bounds, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense, useMemo } from "react";
import { EdgesGeometry, LineBasicMaterial, LineSegments, Mesh, MeshStandardMaterial, type Object3D } from "three";

// Edges only from this angle between neighboring faces, so that fillets do not look hatched
const EDGE_ANGLE_DEG = 25;

function Part({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const part = useMemo(() => {
    const root: Object3D = scene.clone(true);
    const body = new MeshStandardMaterial({ color: "#c9ced6", metalness: 0.15, roughness: 0.55, polygonOffset: true, polygonOffsetFactor: 1 });
    const edge = new LineBasicMaterial({ color: "#2b313a" });
    const meshes: Mesh[] = [];
    root.traverse((o) => { if (o instanceof Mesh) meshes.push(o); });
    for (const m of meshes) {
      m.material = body;
      m.add(new LineSegments(new EdgesGeometry(m.geometry, EDGE_ANGLE_DEG), edge));
    }
    return root;
  }, [scene]);
  return <primitive object={part} />;
}

export default function ModelViewer({ url }: { url: string }) {
  return (
    <Canvas className="cursor-grab" camera={{ position: [1, 0.8, 1.2], fov: 35, near: 0.0001, far: 1000 }} dpr={[1, 2]}>
      <color attach="background" args={["#fbfbfc"]} />
      <hemisphereLight args={["#ffffff", "#b8bec8", 1.6]} />
      <directionalLight position={[3, 5, 4]} intensity={1.6} />
      <directionalLight position={[-4, -2, -3]} intensity={0.5} />
      <Suspense fallback={null}>
        <Bounds fit clip observe margin={1.3}>
          <Part url={url} />
        </Bounds>
      </Suspense>
      <OrbitControls makeDefault />
    </Canvas>
  );
}
