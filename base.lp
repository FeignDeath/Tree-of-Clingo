% Auxillaries (grid and letters)
d(0..4).
l(a;b;c;d;e;f;g;h;i;j;k;l;m;n;o;p;q;r;s;t;u;v;w;x;y;z).

1 {answer(X,Y,L): l(L)} :- d(X), d(Y).

% Set no_duplicates to control for answers with only one letter per field
#external duplicates.
:- answer(X,Y,L1), answer(X,Y,L2), L1<L2, not duplicates.

#show matches(N) : N = {answer(X,Y,L) : sol(X,Y,L)}.
